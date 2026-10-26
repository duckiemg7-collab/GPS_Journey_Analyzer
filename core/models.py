from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from config.settings import FilterSettings


@dataclass(slots=True)
class AnalysisResult:
    details: pd.DataFrame
    daily: pd.DataFrame
    events: pd.DataFrame
    files: list[Path]
    settings: FilterSettings
    logs: list[str] = field(default_factory=list)
    file_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    segments: pd.DataFrame = field(default_factory=pd.DataFrame)
    counter_evidence: pd.DataFrame = field(default_factory=pd.DataFrame)
    reconciliation: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def totals(self) -> dict[str, float | int | None]:
        def total(column: str) -> float | None:
            values = pd.to_numeric(self.daily.get(column), errors="coerce")
            return None if values is None or values.notna().sum() == 0 else float(values.sum())

        totals = {
            "days": int(self.daily["date"].nunique()) if not self.daily.empty else 0,
            "records": int(len(self.details)),
            "device_original_km": total("device_original_km"),
            "device_unallocated_km": total("device_unallocated_km"),
            "unallocated_device_km": total("unallocated_device_km"),
            "gps_filtered_km": total("gps_filtered_km"),
            "gps_unverified_km": total("gps_unverified_km"),
            "device_corrected_km": total("device_corrected_km"),
            "confirmed_false_km": total("confirmed_false_km"),
            "events": int(len(self.events)),
        }
        if not self.reconciliation.empty:
            for target, column in {
                "device_original_km": "device_period_original_km",
                "device_corrected_km": "device_period_corrected_km",
                "raw_records": "raw_records", "valid_records": "valid_records",
                "duplicate_records": "duplicate_records", "excluded_records": "excluded_records",
                "warning_records": "warning_records", "unique_warning_events": "unique_warning_events",
                "gps_raw_km": "gps_raw_km", "gps_confirmed_outlier_km": "gps_confirmed_outlier_km",
                "gap_segments": "gap_segments",
                "signal_loss_segments": "signal_loss_segments",
            }.items():
                value = self.reconciliation[column].sum(min_count=1)
                totals[target] = None if pd.isna(value) else float(value)
        return totals

