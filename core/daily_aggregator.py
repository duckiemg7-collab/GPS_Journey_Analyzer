from __future__ import annotations

import numpy as np
import pandas as pd


def aggregate_daily(details: pd.DataFrame, by_source_file: bool = False) -> pd.DataFrame:
    """Aggregate after deduplication.

    The authoritative total is device + date. ``by_source_file`` is only a
    presentation view used to draw per-file separators in the UI.
    """
    data = details.copy()
    data["date"] = data["timestamp"].dt.date
    usable = data[data["algorithm_status"] != "DUPLICATE"]
    group_columns = ["device_id", "date"]
    if by_source_file:
        group_columns.insert(0, "source_file")
    rows: list[dict[str, object]] = []
    for key, group in usable.groupby(group_columns, dropna=False, sort=True):
        if by_source_file:
            source_file, device, date = key
        else:
            device, date = key
            source_file = None
        group = group.sort_values(["timestamp", "input_order"], kind="stable")
        km = pd.to_numeric(group["device_km"], errors="coerce")
        deltas = km.diff()
        # Positive deltas are real counter progress. Negative deltas are resets
        # and are never subtracted from the reported distance.
        device_original = float(deltas[deltas > 0].sum()) if km.notna().sum() >= 2 else np.nan
        false_km = float(pd.to_numeric(group["confirmed_false_km"], errors="coerce").sum())
        valid_coords = group[["latitude", "longitude"]].notna().all(axis=1).sum()
        gps = (
            float(pd.to_numeric(group["gps_filtered_segment_km"], errors="coerce").sum())
            if valid_coords >= 2
            else np.nan
        )
        unverified = float(pd.to_numeric(group["gps_unverified_segment_km"], errors="coerce").sum())
        corrected = max(0.0, device_original - false_km) if pd.notna(device_original) else np.nan
        warnings = int((group["algorithm_status"] != "VALID").sum())
        statuses = group.loc[group["algorithm_status"] != "VALID", "algorithm_status"].value_counts()
        summary = ", ".join(f"{name}: {count}" for name, count in statuses.items())
        row: dict[str, object] = {
            "date": date,
            "device_id": device,
            "device_original_km": device_original,
            "gps_filtered_km": gps,
            "gps_unverified_km": unverified,
            "device_corrected_km": corrected,
            "confirmed_false_km": false_km,
            "warning_count": warnings,
            "warnings": summary,
            "record_count": int(len(group)),
        }
        if by_source_file:
            row["source_file"] = source_file
        rows.append(row)
    return pd.DataFrame(rows)
