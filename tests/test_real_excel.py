from __future__ import annotations

from pathlib import Path

from core.pipeline import analyze_paths


def test_real_workbook_reads_all_days_and_detects_known_return_jump():
    source = next(Path("file_sample_excel").glob("*50CD00060A.xlsx"))
    result = analyze_paths([source])
    assert len(result.details) == 14020
    assert result.daily["date"].nunique() == 8
    day3 = result.daily[result.daily["date"].astype(str) == "2026-10-03"].iloc[0]
    assert 18.4 <= day3["confirmed_false_km"] <= 18.6
    assert 88.0 <= day3["gps_filtered_km"] <= 90.0
    assert any("XML style" in message for message in result.logs)

