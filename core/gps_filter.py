from __future__ import annotations

import unicodedata

import numpy as np
import pandas as pd

from core.haversine import haversine_km, point_distance_km
from config.settings import FilterSettings


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("đ", "d")


def _append_reason(frame: pd.DataFrame, index: int, reason: str) -> None:
    old = str(frame.at[index, "warning_reason"] or "")
    frame.at[index, "warning_reason"] = f"{old}; {reason}".strip("; ")


def calculate_pair_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    out["device_km"] = pd.to_numeric(out["device_km"], errors="coerce")
    group = out.groupby("device_id", sort=False)
    prev_lat = group["latitude"].shift()
    prev_lon = group["longitude"].shift()
    prev_time = group["timestamp"].shift()
    prev_km = group["device_km"].shift()
    out["delta_time_seconds"] = (out["timestamp"] - prev_time).dt.total_seconds()
    out["raw_distance_km"] = haversine_km(prev_lat, prev_lon, out["latitude"], out["longitude"])
    out["gps_speed_kmh"] = np.where(
        out["delta_time_seconds"] > 0,
        out["raw_distance_km"] / (out["delta_time_seconds"] / 3600.0),
        np.nan,
    )
    out["device_km_delta"] = out["device_km"] - prev_km
    out["device_km_reset"] = out["device_km_delta"] < 0
    out["cross_day"] = out["timestamp"].dt.normalize() != prev_time.dt.normalize()
    out["confirmed_false_km"] = 0.0
    out["gps_filtered_segment_km"] = 0.0
    out["gps_unverified_segment_km"] = 0.0
    out["event_type"] = ""
    return out


def _positive_device_km(frame: pd.DataFrame, indexes: list[int]) -> float:
    values = pd.to_numeric(frame.loc[indexes, "device_km"], errors="coerce")
    deltas = values.diff()
    return float(deltas[deltas > 0].sum()) if deltas.notna().any() else 0.0


def _mark_suspect(frame: pd.DataFrame, index: int, reason: str, event: str) -> None:
    if frame.at[index, "algorithm_status"] in {"INVALID_COORDINATE", "DUPLICATE", "NEED_REVIEW"}:
        return
    frame.at[index, "algorithm_status"] = "SUSPECTED_NOISE"
    frame.at[index, "exclude_from_gps"] = True
    frame.at[index, "event_type"] = event
    _append_reason(frame, index, reason)


def _mark_gap(frame: pd.DataFrame, index: int, reason: str) -> None:
    if frame.at[index, "algorithm_status"] in {"INVALID_COORDINATE", "DUPLICATE"}:
        return
    frame.at[index, "algorithm_status"] = "GPS_GAP"
    frame.at[index, "exclude_from_gps"] = True
    frame.at[index, "event_type"] = "GPS Signal Loss"
    _append_reason(frame, index, reason)


def _confirm_returning_clusters(
    frame: pd.DataFrame,
    indexes: list[int],
    candidate_positions: list[int],
    stop_radius_km: float,
    stop_speed_kmh: float,
) -> None:
    """Confirm a jump/cluster only when the track returns near its anchor."""
    if not candidate_positions:
        return
    runs: list[list[int]] = [[candidate_positions[0]]]
    for position in candidate_positions[1:]:
        if position == runs[-1][-1] + 1:
            runs[-1].append(position)
        else:
            runs.append([position])
    for run_index, run in enumerate(runs):
        start_pos = run[0]
        if start_pos == 0:
            continue
        anchor_pos = start_pos - 1
        anchor_i = indexes[anchor_pos]
        if pd.isna(frame.at[anchor_i, "latitude"]):
            continue
        end_candidates = run[1:]
        if run_index + 1 < len(runs):
            end_candidates.append(runs[run_index + 1][0])
        for end_pos in end_candidates:
            if end_pos - start_pos > 1500:
                break
            end_i = indexes[end_pos]
            if frame.at[end_i, "cross_day"]:
                break
            duration = (frame.at[end_i, "timestamp"] - frame.at[anchor_i, "timestamp"]).total_seconds()
            if pd.isna(duration) or duration <= 0 or duration > 8 * 3600:
                continue
            if pd.isna(frame.at[end_i, "latitude"]):
                continue
            return_distance = point_distance_km(
                frame.at[anchor_i, "latitude"], frame.at[anchor_i, "longitude"],
                frame.at[end_i, "latitude"], frame.at[end_i, "longitude"],
            )
            if return_distance > max(0.15, stop_radius_km * 5):
                continue
            middle = [indexes[pos] for pos in range(start_pos, end_pos)]
            if not middle:
                continue
            speeds = pd.to_numeric(frame.loc[middle, "device_speed_kmh"], errors="coerce")
            statuses = frame.loc[middle, "device_status"].map(_plain)
            stationary = speeds.notna() & (speeds <= stop_speed_kmh)
            stationary |= statuses.str.contains("dung|do|stop", na=False)
            stationary_ratio = float(stationary.mean()) if len(stationary) else 0.0
            internal_km = _positive_device_km(frame, [anchor_i, *middle])
            false_km = _positive_device_km(frame, [anchor_i, *middle, end_i])
            if stationary_ratio < 0.7 or internal_km > 0.3 or (false_km <= 0.3 and len(middle) < 2):
                continue
            label = "GPS Jump and Return" if len(middle) <= 2 else "GPS Cluster Outlier"
            for m in middle:
                if frame.at[m, "algorithm_status"] not in {"INVALID_COORDINATE", "DUPLICATE"}:
                    frame.at[m, "algorithm_status"] = "CONFIRMED_OUTLIER"
                    frame.at[m, "exclude_from_gps"] = True
                    frame.at[m, "event_type"] = label
                    _append_reason(frame, m, f"GPS rời điểm neo rồi quay lại; bằng chứng dừng {stationary_ratio:.0%}")
            if false_km > 0:
                frame.at[end_i, "confirmed_false_km"] = false_km
                frame.at[end_i, "event_type"] = "Device Distance Anomaly"
                _append_reason(frame, end_i, f"Km thiết bị tăng {false_km:.1f} km tại cụm GPS quay về")
            consumed_until = end_pos - 1
            break


def _rebuild_gps_segments(frame: pd.DataFrame, indexes: list[int], speed_limit: float, max_gap_seconds: int) -> None:
    """Rebuild segments from the nearest accepted point, without bridging gaps."""
    anchor_i: int | None = None
    hard_break = True
    for i in indexes:
        status = str(frame.at[i, "algorithm_status"])
        if status in {"INVALID_COORDINATE", "NEED_REVIEW", "GPS_GAP"}:
            hard_break = True
            anchor_i = None
            continue
        if pd.isna(frame.at[i, "latitude"]) or pd.isna(frame.at[i, "timestamp"]):
            hard_break = True
            anchor_i = None
            continue
        if frame.at[i, "exclude_from_gps"]:
            continue
        if anchor_i is None or hard_break:
            anchor_i = i
            hard_break = False
            continue
        dt = (frame.at[i, "timestamp"] - frame.at[anchor_i, "timestamp"]).total_seconds()
        if dt <= 0 or frame.at[i, "cross_day"] or dt > max_gap_seconds:
            raw = frame.at[i, "raw_distance_km"]
            frame.at[i, "gps_unverified_segment_km"] = float(raw) if pd.notna(raw) else 0.0
            hard_break = True
            anchor_i = None
            continue
        distance = point_distance_km(
            frame.at[anchor_i, "latitude"], frame.at[anchor_i, "longitude"],
            frame.at[i, "latitude"], frame.at[i, "longitude"],
        )
        speed = distance / (dt / 3600.0)
        if speed > speed_limit * 1.02:
            _mark_suspect(frame, i, f"Vận tốc nối lại {speed:.1f} km/h vượt ngưỡng {speed_limit:.0f}", "GPS Teleport")
            frame.at[i, "gps_unverified_segment_km"] = distance
            continue
        frame.at[i, "gps_filtered_segment_km"] = distance
        anchor_i = i


def detect_and_filter(frame: pd.DataFrame, settings: FilterSettings) -> pd.DataFrame:
    out = calculate_pair_metrics(frame)
    effective = settings.effective()
    speed_limit = effective.max_plausible_speed_kmh
    stop_radius_km = effective.stop_radius_meters / 1000.0

    for _, indexes_group in out.groupby("device_id", sort=False).groups.items():
        indexes = list(indexes_group)
        candidate_positions: list[int] = []
        statuses_plain = out.loc[indexes, "device_status"].map(_plain)
        speeds = pd.to_numeric(out.loc[indexes, "device_speed_kmh"], errors="coerce")
        explicit_stop = statuses_plain.str.contains("dung|do|stop", na=False)
        signal_loss = statuses_plain.str.contains("mat gps|mat tin hieu", na=False)

        for pos, i in enumerate(indexes):
            if pos == 0:
                continue
            dt = out.at[i, "delta_time_seconds"]
            distance = out.at[i, "raw_distance_km"]
            if pd.isna(dt) or dt <= 0:
                if out.at[i, "algorithm_status"] == "VALID":
                    out.at[i, "algorithm_status"] = "NEED_REVIEW"
                    out.at[i, "exclude_from_gps"] = True
                    out.at[i, "event_type"] = "Timestamp Error"
                    _append_reason(out, i, "Timestamp trùng hoặc không tăng")
                continue
            if pd.isna(distance):
                continue
            if out.at[i, "cross_day"]:
                if distance > stop_radius_km:
                    _mark_gap(out, i, "Đoạn nối qua ngày; không tự cộng quãng đường")
                    out.at[i, "gps_unverified_segment_km"] = float(distance)
                continue
            if signal_loss.iloc[pos] or signal_loss.iloc[pos - 1]:
                _mark_gap(out, i, "Thiết bị báo mất GPS; không tự nối quãng đường")
                out.at[i, "gps_unverified_segment_km"] = float(distance)
                continue
            prev_speed = speeds.iloc[pos - 1]
            current_speed = speeds.iloc[pos]
            both_speed_known = pd.notna(prev_speed) and pd.notna(current_speed)
            stopped_edge = bool(
                (both_speed_known and prev_speed <= settings.stop_speed_kmh and current_speed <= settings.stop_speed_kmh)
                or (explicit_stop.iloc[pos - 1] and explicit_stop.iloc[pos])
            )
            device_delta = out.at[i, "device_km_delta"]
            device_stationary = pd.notna(device_delta) and device_delta <= 0.1
            impossible_speed = pd.notna(out.at[i, "gps_speed_kmh"]) and out.at[i, "gps_speed_kmh"] > speed_limit * 1.02
            stationary_drift = stopped_edge and distance > stop_radius_km and device_stationary
            if dt > effective.max_gps_gap_seconds and distance > stop_radius_km and not (stationary_drift or impossible_speed):
                _mark_gap(out, i, f"Khoảng cách mẫu {dt:.0f} giây; không tự nối quãng đường")
                out.at[i, "gps_unverified_segment_km"] = float(distance)
                continue
            if stationary_drift or impossible_speed:
                candidate_positions.append(pos)
                out.at[i, "gps_unverified_segment_km"] = float(distance)
                if stationary_drift:
                    _mark_suspect(out, i, f"Xe dừng nhưng tọa độ trôi {distance * 1000:.0f} m", "GPS Drift")
                    out.at[i, "algorithm_status"] = "GPS_DRIFT"
                else:
                    _mark_suspect(out, i, f"Vận tốc GPS suy ra {out.at[i, 'gps_speed_kmh']:.1f} km/h vượt ngưỡng {speed_limit:.0f}", "GPS Teleport")

        _confirm_returning_clusters(out, indexes, candidate_positions, stop_radius_km, settings.stop_speed_kmh)
        _rebuild_gps_segments(out, indexes, speed_limit, effective.max_gps_gap_seconds)

    return out
