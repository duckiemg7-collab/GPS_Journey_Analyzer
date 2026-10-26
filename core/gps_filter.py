from __future__ import annotations

import unicodedata
import re

import numpy as np
import pandas as pd

from core.haversine import haversine_km, point_distance_km
from config.settings import FilterSettings


def _plain(value: object) -> str:
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("đ", "d")


def _status_flags(value: object) -> tuple[bool, bool, bool]:
    """Map the status vocabulary found in source Excel files."""
    text = _plain(value).replace("_", " ").replace("-", " ")
    def matches(phrases):
        return any(re.search(r"\b" + re.escape(token) + r"\b", text) for token in phrases)
    stopped = matches(("dung", "do", "stop", "stopped", "park", "parked", "idle", "nghi", "tat may", "engine off"))
    running = matches(("chay", "run", "running", "moving", "di chuyen", "hoat dong"))
    signal_loss = matches(("mat gps", "mat tin hieu", "gps lost", "no gps", "offline", "lost signal"))
    if running or signal_loss:
        stopped = False
    return stopped, running, signal_loss


def _append_reason(frame: pd.DataFrame, index: int, reason: str) -> None:
    old = str(frame.at[index, "warning_reason"] or "")
    frame.at[index, "warning_reason"] = f"{old}; {reason}".strip("; ")


def calculate_pair_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    out["device_km"] = pd.to_numeric(out["device_km"], errors="coerce")
    out["signal_loss_observed"] = out["device_status"].map(_status_flags).map(lambda f: f[2]).groupby(
        [out["device_id"], out["timestamp"]], dropna=False
    ).transform("any")
    eligible = (out["algorithm_status"] != "DUPLICATE") & out["timestamp"].notna()
    eligible &= ~out.duplicated(["device_id", "timestamp"], keep="first")
    out["counter_eligible"] = eligible
    group = out.loc[eligible].groupby("device_id", sort=False)
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
    out["cross_day"] = prev_time.notna() & (out["timestamp"].dt.normalize() != prev_time.reindex(out.index).dt.normalize())
    positive_delta = out["device_km_delta"].clip(lower=0).where(eligible)
    out["device_allocated_segment_km"] = positive_delta.where(~out["cross_day"], 0)
    out["unallocated_device_segment_km"] = positive_delta.where(out["cross_day"], 0)
    # Stable row indexes refer to details rows, not source Excel row numbers.
    out["pair_start_index"] = pd.Series(out.index, index=out.index).loc[eligible].groupby(out.loc[eligible, "device_id"]).shift()
    out["confirmed_false_km"] = 0.0
    out["gps_filtered_segment_km"] = 0.0
    out["gps_unverified_segment_km"] = 0.0
    out["gps_unverified_start_index"] = pd.NA
    out["gps_unverified_end_index"] = pd.NA
    out["gps_unverified_reason"] = ""
    out["event_type"] = ""
    out["device_anomaly_status"] = ""
    out["device_suspected_km"] = 0.0
    for column in ("gps_segment_start_index", "gps_segment_end_index", "gps_segment_raw_km", "gps_segment_seconds", "gps_segment_reference_km"):
        out[column] = np.nan
    out["gps_segment_class"] = ""
    out["gps_segment_reason"] = ""
    out["gps_confirmed_outlier_segment_km"] = 0.0
    return out


def _confirmed_counter_anomaly(
    frame: pd.DataFrame, anchor_i: int, middle: list[int], end_i: int
) -> float:
    """GPS evidence alone cannot establish an exact false odometer amount.

    A frozen counter can be a delayed upload; a decrease can be a reset. Both
    invalidate the old assumption that the whole return delta is fictitious.
    Keep the hook for independently verified evidence; currently none exists.
    """
    values = pd.to_numeric(frame.loc[[anchor_i, *middle, end_i], "device_km"], errors="coerce")
    if values.isna().any():
        return 0.0
    return 0.0


def _record_unverified(
    frame: pd.DataFrame,
    end_i: int,
    start_i: int | None,
    distance: float | int | None,
    reason: str,
) -> None:
    if start_i is None or pd.isna(distance):
        return
    frame.at[end_i, "gps_unverified_segment_km"] = float(distance)
    frame.at[end_i, "gps_unverified_start_index"] = int(start_i)
    frame.at[end_i, "gps_unverified_end_index"] = int(end_i)
    frame.at[end_i, "gps_unverified_reason"] = reason


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
    consumed_until = -1
    for run_index, run in enumerate(runs):
        start_pos = run[0]
        if start_pos == 0 or start_pos <= consumed_until:
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
            if frame.loc[[indexes[p] for p in range(start_pos, end_pos + 1)], "cross_day"].any():
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
            excursion = point_distance_km(
                frame.at[anchor_i, "latitude"], frame.at[anchor_i, "longitude"],
                frame.at[middle[0], "latitude"], frame.at[middle[0], "longitude"],
            )
            if excursion <= max(.15, stop_radius_km * 5):
                continue
            speeds = pd.to_numeric(frame.loc[middle, "device_speed_kmh"], errors="coerce")
            statuses = frame.loc[middle, "device_status"].map(_status_flags)
            stationary = speeds.notna() & (speeds <= stop_speed_kmh)
            stationary |= statuses.map(lambda flags: flags[0]) & ~(speeds > stop_speed_kmh)
            stationary_ratio = float(stationary.mean()) if len(stationary) else 0.0
            internal_counter = pd.to_numeric(frame.loc[[anchor_i, *middle], "device_km"], errors="coerce").diff().clip(lower=0).sum()
            false_km = _confirmed_counter_anomaly(frame, anchor_i, middle, end_i)
            if stationary_ratio < 0.7 or internal_counter > .3 or (len(middle) < 2 and return_distance > stop_radius_km):
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
    """Partition raw intervals into nonoverlapping spans, then rebuild safe spans.

    Raw removed km are diagnostic geometry, not additive to rebuilt route km.
    Unverified km are endpoint straight-line references, never actual mileage.
    """
    frame.loc[indexes, "gps_unverified_segment_km"] = 0.0
    frame.loc[indexes, "gps_unverified_reason"] = ""
    frame.loc[indexes, ["gps_unverified_start_index", "gps_unverified_end_index"]] = pd.NA
    anchor_pos = 0
    pending = False
    lat = frame["latitude"].to_numpy()
    lon = frame["longitude"].to_numpy()
    times = frame["timestamp"]
    local = frame.loc[indexes]
    raw_values = local["raw_distance_km"].to_numpy(dtype=float)
    raw_cumulative = np.cumsum(np.nan_to_num(raw_values))
    raw_known = np.cumsum(~np.isnan(raw_values))
    confirmed = local["algorithm_status"].eq("CONFIRMED_OUTLIER").to_numpy()
    bad_edge = confirmed | np.r_[False, confirmed[:-1]]
    removed_cumulative = np.cumsum(np.where(bad_edge, np.nan_to_num(raw_values), 0))
    edge_break = local["cross_day"].to_numpy() | local["delta_time_seconds"].gt(max_gap_seconds).to_numpy()
    loss = local["signal_loss_observed"].to_numpy()
    invalid = local["invalid_coordinate"].to_numpy()
    point_break = loss | invalid
    barrier_cumulative = np.cumsum(edge_break | point_break | np.r_[False, point_break[:-1]])

    def distance(a, b):
        if frame.at[a, "invalid_coordinate"] or frame.at[b, "invalid_coordinate"]:
            return np.nan
        if not np.isfinite([lat[a], lon[a], lat[b], lon[b]]).all():
            return np.nan
        return point_distance_km(lat[a], lon[a], lat[b], lon[b])

    def emit(start_pos, end_pos, kind, reason):
        a, b = indexes[start_pos], indexes[end_pos]
        d = distance(a, b)
        dt = (times.iat[b] - times.iat[a]).total_seconds()
        raw = raw_cumulative[end_pos] - raw_cumulative[start_pos] if raw_known[end_pos] > raw_known[start_pos] else np.nan
        removed = removed_cumulative[end_pos] - removed_cumulative[start_pos]
        frame.at[b, "gps_segment_start_index"] = a
        frame.at[b, "gps_segment_end_index"] = b
        frame.at[b, "gps_segment_class"] = kind
        frame.at[b, "gps_segment_reason"] = reason
        frame.at[b, "gps_segment_raw_km"] = raw
        frame.at[b, "gps_segment_seconds"] = dt
        frame.at[b, "gps_segment_reference_km"] = d
        frame.at[b, "gps_confirmed_outlier_segment_km"] = removed
        if kind == "TRUSTED":
            frame.at[b, "gps_filtered_segment_km"] = d
        elif kind == "UNVERIFIED":
            frame.at[b, "gps_unverified_segment_km"] = d
            _record_unverified(frame, b, a, d, reason)

    for pos in range(1, len(indexes)):
        i, a = indexes[pos], indexes[anchor_pos]
        dt = (frame.at[i, "timestamp"] - frame.at[a, "timestamp"]).total_seconds()
        d = distance(a, i)
        status = frame.at[i, "algorithm_status"]
        barrier = barrier_cumulative[pos] > barrier_cumulative[anchor_pos]
        if status == "CONFIRMED_OUTLIER" or invalid[pos]:
            pending = True
            if pos == len(indexes) - 1:
                emit(anchor_pos, pos, "OUTLIER" if status == "CONFIRMED_OUTLIER" else "UNVERIFIED", "Confirmed bad GPS geometry" if status == "CONFIRMED_OUTLIER" else "Missing coordinate fix; reference unavailable")
            continue
        if barrier or pd.isna(d):
            emit(anchor_pos, pos, "UNVERIFIED", "Signal/time/day/coordinate gap; straight-line reference only")
            anchor_pos, pending = pos, False
            continue
        plausible = dt > 0 and d * 3600 / dt <= speed_limit * 1.02
        # A trusted return needs a following plausible sample, or independent
        # stationary evidence. Never accept a raw teleport on speed alone.
        is_return = False
        if pending and plausible and status in {"SUSPECTED_NOISE", "GPS_DRIFT"} and pos + 1 < len(indexes):
            nxt = indexes[pos + 1]
            ndt = (frame.at[nxt, "timestamp"] - frame.at[i, "timestamp"]).total_seconds()
            nd = distance(i, nxt)
            is_return = (0 < ndt <= max_gap_seconds and pd.notna(nd) and nd * 3600 / ndt <= speed_limit * 1.02
                         and frame.at[nxt, "algorithm_status"] == "VALID"
                         and frame.at[i, "algorithm_status"] != "CONFIRMED_OUTLIER")
        if frame.at[i, "exclude_from_gps"] and not is_return:
            pending = True
            if pos == len(indexes) - 1:
                emit(anchor_pos, pos, "UNVERIFIED", "Unresolved GPS outlier; straight-line reference only")
            continue
        if plausible and dt <= max_gap_seconds:
            if is_return:
                frame.at[i, "exclude_from_gps"] = False
                _append_reason(frame, i, "Rebuilt from accepted anchor; raw incoming jump remains excluded")
            emit(anchor_pos, pos, "TRUSTED", "Rebuilt accepted endpoints" if pending else "Continuous accepted endpoints")
            anchor_pos, pending = pos, False
        elif pending and frame.at[i, "algorithm_status"] == "VALID":
            prev_pos = pos - 1
            prev = indexes[prev_pos]
            raw_dt = frame.at[i, "delta_time_seconds"]
            raw_d = distance(prev, i)
            if prev_pos > anchor_pos and not confirmed[prev_pos] and 0 < raw_dt <= max_gap_seconds and raw_d * 3600 / raw_dt <= speed_limit * 1.02:
                emit(anchor_pos, prev_pos, "UNVERIFIED", "Relocated GPS; incoming route unknown")
                emit(prev_pos, pos, "TRUSTED", "Continuous samples after GPS reacquisition")
            else:
                emit(anchor_pos, pos, "UNVERIFIED", "Reacquired GPS; intervening route unknown")
            anchor_pos, pending = pos, False
        else:
            _mark_suspect(frame, i, "Rebuilt segment exceeds speed/time limit", "GPS Teleport")
            pending = True
            if pos == len(indexes) - 1:
                emit(anchor_pos, pos, "UNVERIFIED", "Unresolved teleport; straight-line reference only")


def detect_and_filter(frame: pd.DataFrame, settings: FilterSettings) -> pd.DataFrame:
    out = calculate_pair_metrics(frame)
    effective = settings.effective()
    speed_limit = effective.max_plausible_speed_kmh
    stop_radius_km = effective.stop_radius_meters / 1000.0

    for _, indexes_group in out.groupby("device_id", sort=False).groups.items():
        indexes = [i for i in indexes_group if out.at[i, "counter_eligible"]]
        if not indexes:
            continue
        candidate_positions: list[int] = []
        status_flags = out.loc[indexes, "device_status"].map(_status_flags)
        speeds = pd.to_numeric(out.loc[indexes, "device_speed_kmh"], errors="coerce")
        explicit_stop = status_flags.map(lambda flags: flags[0])
        signal_loss = out.loc[indexes, "signal_loss_observed"]

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
                    _record_unverified(out, i, indexes[pos - 1], distance, "GPS day boundary")
                continue
            if signal_loss.iloc[pos] or signal_loss.iloc[pos - 1]:
                _mark_gap(out, i, "Thiết bị báo mất GPS; không tự nối quãng đường")
                _record_unverified(out, i, indexes[pos - 1], distance, "Signal loss")
                continue
            prev_speed = speeds.iloc[pos - 1]
            current_speed = speeds.iloc[pos]
            both_speed_known = pd.notna(prev_speed) and pd.notna(current_speed)
            stopped_edge = bool(
                (both_speed_known and prev_speed <= settings.stop_speed_kmh and current_speed <= settings.stop_speed_kmh)
                or (explicit_stop.iloc[pos - 1] and explicit_stop.iloc[pos]
                    and not (pd.notna(prev_speed) and prev_speed > settings.stop_speed_kmh)
                    and not (pd.notna(current_speed) and current_speed > settings.stop_speed_kmh))
            )
            device_delta = out.at[i, "device_km_delta"]
            device_stationary = pd.notna(device_delta) and 0 <= device_delta <= 0.1 + 1e-9
            impossible_speed = pd.notna(out.at[i, "gps_speed_kmh"]) and out.at[i, "gps_speed_kmh"] > speed_limit * 1.02
            stationary_drift = stopped_edge and distance > stop_radius_km and device_stationary
            if dt > effective.max_gps_gap_seconds and distance > stop_radius_km and not (stationary_drift or impossible_speed):
                _mark_gap(out, i, f"Khoảng cách mẫu {dt:.0f} giây; không tự nối quãng đường")
                _record_unverified(out, i, indexes[pos - 1], distance, "GPS gap")
                continue
            if stationary_drift or impossible_speed:
                candidate_positions.append(pos)
                _record_unverified(out, i, indexes[pos - 1], distance, "Stationary drift" if stationary_drift else "GPS teleport")
                if stationary_drift:
                    _mark_suspect(out, i, f"Xe dừng nhưng tọa độ trôi {distance * 1000:.0f} m", "GPS Drift")
                    if out.at[i, "algorithm_status"] == "SUSPECTED_NOISE":
                        out.at[i, "algorithm_status"] = "GPS_DRIFT"
                else:
                    _mark_suspect(out, i, f"Vận tốc GPS suy ra {out.at[i, 'gps_speed_kmh']:.1f} km/h vượt ngưỡng {speed_limit:.0f}", "GPS Teleport")

        _confirm_returning_clusters(out, indexes, candidate_positions, stop_radius_km, settings.stop_speed_kmh)
        _rebuild_gps_segments(out, indexes, speed_limit, effective.max_gps_gap_seconds)

    # Counter evidence is independent of the GPS class. No exact false amount
    # can be proven solely by a coordinate excursion or delayed counter upload.
    positive = out["device_km_delta"].gt(0) & out["counter_eligible"]
    counter_speed = out["device_km_delta"] * 3600 / out["delta_time_seconds"]
    suspect = positive & (out["algorithm_status"].isin(["CONFIRMED_OUTLIER", "SUSPECTED_NOISE", "GPS_DRIFT"])
                          | counter_speed.gt(speed_limit * 1.02))
    out.loc[suspect, "device_suspected_km"] = out.loc[suspect, "device_km_delta"]
    out.loc[suspect, "device_anomaly_status"] = "NEED_REVIEW"
    out.loc[suspect, "warning_reason"] += "; Counter increase needs independent evidence; no deduction"

    return out
