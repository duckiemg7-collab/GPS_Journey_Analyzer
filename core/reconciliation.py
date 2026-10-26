"""Traceable segment and counter evidence views; source rows remain untouched."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.daily_aggregator import warning_mask


def assign_warning_events(details: pd.DataFrame) -> pd.DataFrame:
    data = details.copy()
    warning = warning_mask(data)
    category = data["algorithm_status"].astype(str) + ":" + data["device_anomaly_status"].astype(str)
    new = (category.ne(category.shift()) | data.device_id.ne(data.device_id.shift())
           | data.timestamp.dt.date.ne(data.timestamp.shift().dt.date)
           | data.delta_time_seconds.gt(120) | ~warning.shift(fill_value=False)) & warning
    data["warning_event_id"] = new.cumsum().where(warning).astype("Int64")
    return data


def endpoint_view(details: pd.DataFrame, start_column: str, end_column: str, mask=None) -> pd.DataFrame:
    selected = details[details[start_column].notna() & (mask if mask is not None else True)]
    keep = ["device_id", "source_file", "source_sheet", "source_row", "timestamp", "latitude", "longitude", "device_km", "device_status", "device_speed_kmh"]
    metrics = ["pair_start_index", "gps_segment_start_index", "gps_segment_end_index", "gps_segment_class", "gps_segment_reason", "gps_segment_seconds", "gps_segment_reference_km", "gps_segment_raw_km", "gps_filtered_segment_km", "gps_unverified_segment_km", "gps_confirmed_outlier_segment_km", "device_km_delta", "raw_distance_km", "delta_time_seconds", "gps_speed_kmh", "device_suspected_km", "confirmed_false_km", "device_anomaly_status"]
    result = selected.reindex(columns=keep + metrics).copy()
    for prefix, column in (("start", start_column), ("end", end_column)):
        indexes = selected[column].astype(int)
        for field in keep:
            result[f"{prefix}_{field}"] = details.loc[indexes, field].to_numpy()
    return result


def segment_view(details: pd.DataFrame) -> pd.DataFrame:
    data = endpoint_view(details, "gps_segment_start_index", "gps_segment_end_index")
    progress = details.device_km_delta.clip(lower=0).fillna(0).where(details.counter_eligible, 0).groupby(details.device_id).cumsum()
    starts = data.gps_segment_start_index.astype(int)
    ends = data.gps_segment_end_index.astype(int)
    data["device_counter_span_km"] = progress.loc[ends].to_numpy() - progress.loc[starts].to_numpy()
    data["reference_kind"] = "Haversine endpoint straight line; actual route unknown for UNVERIFIED"
    data["actual_unverified_km"] = np.nan
    data["segment_id"] = data.device_id.astype(str) + ":" + data.gps_segment_start_index.astype("Int64").astype(str) + ":" + data.gps_segment_end_index.astype("Int64").astype(str)
    return data


def counter_evidence_view(details: pd.DataFrame) -> pd.DataFrame:
    mask = details.device_suspected_km.gt(0) | details.confirmed_false_km.gt(0)
    evidence = endpoint_view(details, "pair_start_index", "pair_start_index", mask)
    # The counter endpoint is the current row; start is its canonical predecessor.
    for field in ("timestamp", "latitude", "longitude", "device_km", "source_file", "source_sheet", "source_row", "device_status", "device_speed_kmh"):
        evidence[f"end_{field}"] = evidence[field]
    evidence = evidence[(evidence.device_suspected_km > 0) | (evidence.confirmed_false_km > 0)].copy()
    evidence["counter_speed_kmh"] = evidence.device_km_delta * 3600 / evidence.delta_time_seconds
    evidence["deducted_km"] = evidence.confirmed_false_km
    evidence["confirmation_status"] = np.where(evidence.confirmed_false_km > 0, "CONFIRMED", "NEED_REVIEW")
    evidence["evidence"] = "GPS/counter inconsistency; delayed upload, movement and reset cannot be ruled out. No exact false amount proven."
    evidence["counter_edge_id"] = evidence.device_id.astype(str) + ":" + evidence.pair_start_index.astype("Int64").astype(str) + ":" + evidence.index.astype(str)
    return evidence


def period_reconciliation(details: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for device, group in details.groupby("device_id", sort=True):
        canonical = group[group.counter_eligible].sort_values(["timestamp", "input_order"])
        independent = canonical.device_km.diff().clip(lower=0).sum(min_count=1)
        days = daily[daily.device_id == device]
        allocated = days.device_original_km.sum(min_count=1)
        unallocated = days.unallocated_device_km.sum(min_count=1)
        difference = independent - (allocated + unallocated)
        rows.append({
            "device_id": device, "device_period_original_km": independent,
            "device_daily_allocated_km": allocated, "unallocated_device_km": unallocated,
            "counter_reconciliation_difference_km": difference,
            "raw_records": len(group), "valid_records": int((~warning_mask(group)).sum()),
            "duplicate_records": int(group.is_duplicate.sum()),
            "excluded_records": int(group.exclude_from_gps.sum()),
            "invalid_timestamp_records": int(group.invalid_timestamp.sum()),
            "warning_records": int(warning_mask(group).sum()),
            "unique_warning_events": group.warning_event_id.nunique(),
            "gps_raw_km": canonical.raw_distance_km.sum(min_count=1),
            "gps_filtered_km": canonical.gps_filtered_segment_km.sum(min_count=1),
            "gps_unverified_km": canonical.gps_unverified_segment_km.sum(min_count=1),
            "gps_confirmed_outlier_km": canonical.gps_confirmed_outlier_segment_km.sum(),
            "confirmed_false_km": canonical.confirmed_false_km.sum(),
            "device_period_corrected_km": independent - canonical.confirmed_false_km.sum(),
            "gap_segments": int(canonical.gps_segment_class.eq("UNVERIFIED").sum()),
            "signal_loss_segments": int((canonical.signal_loss_observed | canonical.signal_loss_observed.shift(fill_value=False)).sum()),
            "counter_resets": int(canonical.device_km_reset.sum()),
        })
    return pd.DataFrame(rows)


def validate_reconciliation(details: pd.DataFrame, segments: pd.DataFrame, reconciliation: pd.DataFrame) -> None:
    """Fail visibly if a distance span overlaps or disappears from the ledger."""
    for device, canonical in details[details.counter_eligible].groupby("device_id", sort=False):
        positions = {index: position for position, index in enumerate(canonical.index)}
        spans = segments[segments.device_id == device]
        previous = 0
        for row in spans.itertuples():
            start = positions[int(row.gps_segment_start_index)]
            end = positions[int(row.gps_segment_end_index)]
            if start != previous or end <= start:
                raise ValueError(f"Overlapping/missing GPS interval: {device}, {start}:{end}")
            previous = end
            if row.gps_filtered_segment_km > 0 and row.gps_unverified_segment_km > 0:
                raise ValueError(f"Distance counted twice: {device}, {start}:{end}")
        if previous != max(0, len(canonical) - 1):
            raise ValueError(f"Unclassified final GPS interval: {device}")
        if not np.isclose(spans.gps_segment_raw_km.sum(), canonical.raw_distance_km.sum(), atol=1e-7):
            raise ValueError(f"Raw GPS reconciliation failed: {device}")
    diff = reconciliation.counter_reconciliation_difference_km.dropna()
    if not np.allclose(diff, 0, atol=1e-7):
        raise ValueError("Device period/day reconciliation failed")
