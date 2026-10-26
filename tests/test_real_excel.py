from __future__ import annotations

from pathlib import Path

from core.pipeline import analyze_paths


def test_real_workbook_reads_and_reconciles_without_fixture_specific_targets():
    source = next(Path("file_sample_excel").glob("*50CD00060A.xlsx"))
    result = analyze_paths([source])
    assert len(result.details) > 0
    assert result.daily["date"].nunique() > 0
    assert (result.daily["gps_filtered_km"].dropna() >= 0).all()
    assert (result.daily["gps_unverified_km"] >= 0).all()
    assert (result.daily["confirmed_false_km"] >= 0).all()
    assert not (
        (result.details["gps_filtered_segment_km"] > 0)
        & (result.details["gps_unverified_segment_km"] > 0)
    ).any()
    assert any("XML style" in message for message in result.logs)

