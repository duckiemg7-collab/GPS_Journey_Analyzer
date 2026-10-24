from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.settings import FilterSettings
from core.daily_aggregator import aggregate_daily
from core.excel_reader import read_excel_files
from core.gps_filter import detect_and_filter
from core.gps_validator import validate_and_sort
from core.models import AnalysisResult


def analyze_paths(
    paths: list[str | Path], settings: FilterSettings | None = None
) -> AnalysisResult:
    settings = settings or FilterSettings()
    raw, files, logs = read_excel_files(paths)
    validated = validate_and_sort(raw)
    details = detect_and_filter(validated, settings)
    daily = aggregate_daily(details)
    file_daily = aggregate_daily(details, by_source_file=True)
    event_mask = (details["algorithm_status"] != "VALID") | (
        details["confirmed_false_km"] > 0
    )
    events = details.loc[event_mask].copy()
    logs.append(
        f"Hoàn tất: {len(details):,} bản ghi, {len(events):,} sự kiện, "
        f"{daily['date'].nunique() if not daily.empty else 0} ngày."
    )
    return AnalysisResult(details, daily, events, files, settings, logs, file_daily)
