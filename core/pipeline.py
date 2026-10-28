from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.settings import FilterSettings
from core.daily_aggregator import aggregate_daily, warning_mask
from core.excel_reader import read_excel_files
from core.gps_filter import detect_and_filter
from core.gps_validator import validate_and_sort
from core.models import AnalysisResult
from core.reconciliation import assign_warning_events, segment_view, counter_evidence_view, period_reconciliation, validate_reconciliation


def analyze_paths(
    paths: list[str | Path], settings: FilterSettings | None = None
) -> AnalysisResult:
    settings = settings or FilterSettings()
    raw, files, logs = read_excel_files(paths)
    return analyze_records(raw, files, settings, logs)


def analyze_records(
    raw: pd.DataFrame, files: list[Path], settings: FilterSettings | None = None,
    logs: list[str] | None = None,
) -> AnalysisResult:
    """Same analysis for source ingestion and reproducible cached audit data."""
    settings = settings or FilterSettings()
    logs = list(logs or [])
    validated = validate_and_sort(raw)
    effective = settings.effective()
    logs.append(f"Cấu hình nhập: {settings.describe()}")
    logs.append(
        "Cấu hình thực truyền vào detect_and_filter: "
        f"{effective.describe(effective=False)}"
    )
    details = assign_warning_events(detect_and_filter(validated, settings))
    daily = aggregate_daily(details)
    file_daily = aggregate_daily(details, by_source_file=True)
    event_mask = warning_mask(details) | details["confirmed_false_km"].gt(0)
    events = details.loc[event_mask].copy()
    logs.append(
        f"Hoàn tất: {len(details):,} bản ghi, {len(events):,} bản ghi có cảnh báo, "
        f"{daily['date'].nunique() if not daily.empty else 0} ngày."
    )
    reconciliation = period_reconciliation(details, daily)
    segments = segment_view(details)
    validate_reconciliation(details, segments, reconciliation)
    logs.append("Bản ghi/cảnh báo theo ngày bao gồm duplicate; valid = không có cảnh báo. Sự kiện = nhóm cảnh báo liên tiếp cùng loại, thiết bị/ngày, cách nhau tối đa 120 giây.")
    logs.append("Km chưa xác minh là Haversine tham khảo, không phải km thực tế. Km thiết bị qua ngày chưa phân bổ được giữ riêng; GPS outlier không tự chứng minh km công tơ sai.")
    return AnalysisResult(details, daily, events, files, settings, logs, file_daily,
                          segments, counter_evidence_view(details), reconciliation)
