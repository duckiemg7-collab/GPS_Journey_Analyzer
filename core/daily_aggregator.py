from __future__ import annotations

import numpy as np
import pandas as pd

from core.display_labels import warning_status_label


def warning_mask(data: pd.DataFrame) -> pd.Series:
    return data["algorithm_status"].ne("VALID") | data.get(
        "device_anomaly_status", pd.Series("", index=data.index)
    ).eq("NEED_REVIEW")


def aggregate_daily(details: pd.DataFrame, by_source_file: bool = False) -> pd.DataFrame:
    """Allocate canonical edges once, then present all source records.

    Cross-day km remain unallocated; their endpoint date is an audit bucket.
    File views reuse the same edges rather than re-diffing each source file.
    """
    data = details.copy()
    data["date"] = data["timestamp"].dt.date
    keys = (["source_file"] if by_source_file else []) + ["device_id", "date"]
    rows = []
    for key, group in data.groupby(keys, dropna=False, sort=True):
        device, date = key[-2:]
        canonical = group[group["counter_eligible"]]
        km = pd.to_numeric(canonical["device_allocated_segment_km"], errors="coerce")
        original = km.sum(min_count=1)
        unallocated = canonical["unallocated_device_segment_km"].sum(min_count=1)
        false_km = canonical["confirmed_false_km"].sum()
        gps_known = (~canonical.invalid_coordinate).sum() >= 2
        gps = canonical["gps_filtered_segment_km"].sum() if gps_known else np.nan
        unverified = canonical.loc[canonical.gps_segment_class.eq("UNVERIFIED"), "gps_unverified_segment_km"]
        warning = warning_mask(group)
        labels = group["algorithm_status"].where(group["algorithm_status"].ne("VALID"), "DEVICE_NEED_REVIEW")
        statuses = labels.loc[warning].map(warning_status_label).value_counts()
        row = {
            "date": date, "device_id": device,
            "device_original_km": original,
            "device_unallocated_km": unallocated,
            "unallocated_device_km": unallocated,
            "gps_raw_km": canonical["raw_distance_km"].sum(min_count=1),
            "gps_filtered_km": gps,
            "gps_unverified_km": unverified.sum(min_count=1) if len(unverified) else 0.0,
            "unverified_unknown_reference_count": int(unverified.isna().sum()),
            "gps_confirmed_outlier_km": canonical["gps_confirmed_outlier_segment_km"].sum(),
            "device_corrected_km": original - false_km if pd.notna(original) else np.nan,
            "confirmed_false_km": false_km,
            "warning_count": int(warning.sum()),
            "warnings": ", ".join(f"{status}: {count}" for status, count in statuses.items()),
            "record_count": len(group),
            "valid_record_count": int((group["algorithm_status"].eq("VALID") & ~warning).sum()),
            "duplicate_record_count": int(group["is_duplicate"].sum()),
            "excluded_record_count": int(group["exclude_from_gps"].sum()),
            "gap_count": int(group["gps_segment_class"].eq("UNVERIFIED").sum()),
            "unique_warning_events": group.loc[warning, "warning_event_id"].nunique() if "warning_event_id" in group else int(warning.sum()),
        }
        if by_source_file:
            row["source_file"] = key[0]
        rows.append(row)
    return pd.DataFrame(rows)
