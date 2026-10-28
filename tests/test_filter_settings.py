from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from config.settings import FilterSettings
from core.gps_filter import detect_and_filter
from core.gps_validator import validate_and_sort
from core.pipeline import analyze_records
from tests.conftest import make_frame
from ui.main_window import AnalysisWorker, MainWindow, build_settings_comparison
from ui.settings_panel import SettingsPage


KM_PER_LONGITUDE_DEGREE_AT_EQUATOR = 111.1950802335329


def _longitude(km: float) -> float:
    return km / KM_PER_LONGITUDE_DEGREE_AT_EQUATOR


def _filtered(rows, settings: FilterSettings):
    return detect_and_filter(validate_and_sort(make_frame(rows)), settings)


def test_max_speed_changes_warning_and_numeric_gps_result():
    rows = [
        ("2026-10-01 08:00:00", 0, _longitude(0), 30, 10),
        ("2026-10-01 08:00:30", 0, _longitude(0.300), 30, 10.3),
    ]
    low = _filtered(rows, FilterSettings(max_plausible_speed_kmh=20))
    high = _filtered(rows, FilterSettings(max_plausible_speed_kmh=80))

    assert low.iloc[1].gps_speed_kmh == pytest.approx(36.0, rel=0.01)
    assert low.iloc[1].algorithm_status == "SUSPECTED_NOISE"
    assert low.iloc[1].gps_filtered_segment_km == 0
    assert high.iloc[1].algorithm_status == "VALID"
    assert high.iloc[1].gps_filtered_segment_km == pytest.approx(0.300, rel=0.01)


def test_max_gap_changes_segment_classification():
    rows = [
        ("2026-10-01 08:00:00", 0, _longitude(0), 10, 10),
        ("2026-10-01 08:01:30", 0, _longitude(0.100), 10, 10.1),
    ]
    short = _filtered(rows, FilterSettings(max_gps_gap_seconds=60))
    long = _filtered(rows, FilterSettings(max_gps_gap_seconds=180))

    assert short.iloc[1].algorithm_status == "GPS_GAP"
    assert short.iloc[1].gps_segment_class == "UNVERIFIED"
    assert long.iloc[1].algorithm_status == "VALID"
    assert long.iloc[1].gps_segment_class == "TRUSTED"


def test_stop_radius_changes_stationary_drift_decision():
    rows = [
        ("2026-10-01 08:00:00", 0, _longitude(0), 0, 10, "Dừng"),
        ("2026-10-01 08:01:00", 0, _longitude(0.040), 0, 10, "Dừng"),
    ]
    narrow = _filtered(rows, FilterSettings(stop_radius_meters=30))
    wide = _filtered(rows, FilterSettings(stop_radius_meters=50))

    assert narrow.iloc[1].algorithm_status == "GPS_DRIFT"
    assert wide.iloc[1].algorithm_status == "VALID"


def test_stop_speed_changes_stationary_evidence():
    rows = [
        ("2026-10-01 08:00:00", 0, _longitude(0), 4, 10),
        ("2026-10-01 08:01:00", 0, _longitude(0.040), 4, 10),
    ]
    strict = _filtered(rows, FilterSettings(stop_speed_kmh=3))
    permissive = _filtered(rows, FilterSettings(stop_speed_kmh=5))

    assert strict.iloc[1].algorithm_status == "VALID"
    assert permissive.iloc[1].algorithm_status == "GPS_DRIFT"


def test_modes_have_distinct_near_boundary_sensitivity():
    rows = [
        ("2026-10-01 08:00:00", 0, _longitude(0), 30, 10),
        ("2026-10-01 08:00:30", 0, _longitude(0.700), 30, 10.7),
        ("2026-10-01 08:01:00", 0, _longitude(1.500), 30, 11.5),
    ]
    counts = {}
    for mode in ("Conservative", "Balanced", "Aggressive"):
        data = _filtered(rows, FilterSettings(max_plausible_speed_kmh=100, mode=mode))
        counts[mode] = int(data.algorithm_status.eq("SUSPECTED_NOISE").sum())

    assert counts == {"Conservative": 0, "Balanced": 1, "Aggressive": 2}


def test_worker_passes_exact_settings(monkeypatch):
    expected = FilterSettings(80, 4, 45, 180, "Balanced")
    captured = {}

    def fake_analyze(paths, settings):
        captured["paths"] = paths
        captured["settings"] = settings
        return "ok"

    monkeypatch.setattr("ui.main_window.analyze_paths", fake_analyze)
    worker = AnalysisWorker(["sample.xlsx"], expected)
    emitted = []
    worker.finished.connect(emitted.append)
    worker.run()

    assert captured == {"paths": ["sample.xlsx"], "settings": expected}
    assert emitted == ["ok"]


def test_save_and_apply_button_emits_real_gui_values():
    app = QApplication.instance() or QApplication([])
    page = SettingsPage()
    page.mode.setCurrentText("Balanced")
    page.max_speed.setValue(88)
    page.stop_speed.setValue(4)
    page.stop_radius.setValue(44)
    page.gap.setValue(181)
    emitted = []
    page.recalculate_requested.connect(emitted.append)
    button = next(button for button in page.findChildren(QPushButton) if button.text() == "Lưu và áp dụng")
    button.click()
    app.processEvents()

    assert emitted == [FilterSettings(88, 4, 44, 181, "Balanced")]
    assert "76.296 km/h" in page.effective_label.text()


def test_settings_change_with_existing_result_starts_reanalysis(monkeypatch):
    app = QApplication.instance() or QApplication([])
    raw = make_frame([
        ("2026-10-01 08:00:00", 0, 0, 10, 1),
        ("2026-10-01 08:01:00", 0, _longitude(0.1), 10, 1.1),
    ])
    result = analyze_records(raw, [Path("synthetic.xlsx")])
    window = MainWindow()
    window._analysis_done(result)
    requested = []

    def fake_start(settings, **kwargs):
        requested.append((settings, kwargs))

    monkeypatch.setattr(window, "start_analysis", fake_start)
    changed = FilterSettings(max_plausible_speed_kmh=80)
    window._settings_changed(changed)

    assert requested == [(changed, {"reason": "settings", "comparison_base": result})]
    window.close()


def test_only_latest_settings_are_queued_while_worker_runs(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(initial_paths=["synthetic.xlsx"])
    active = FilterSettings(max_plausible_speed_kmh=100)
    window._active_settings = active
    monkeypatch.setattr(window, "_analysis_running", lambda: True)

    window._settings_changed(FilterSettings(max_plausible_speed_kmh=90))
    latest = FilterSettings(max_plausible_speed_kmh=80, mode="Balanced")
    window._settings_changed(latest)

    assert window._queued_settings == latest
    window._settings_changed(active)
    assert window._queued_settings is None
    window.close()


def test_unchanged_classification_is_explained():
    rows = [
        ("2026-10-01 08:00:00", 0, 0, 10, 1),
        ("2026-10-01 08:01:00", 0, _longitude(0.1), 10, 1.1),
    ]
    before = analyze_records(make_frame(rows), [], FilterSettings(max_plausible_speed_kmh=120))
    after = analyze_records(make_frame(rows), [], FilterSettings(max_plausible_speed_kmh=130))

    text = build_settings_comparison(before, after)
    assert "Số đoạn thay đổi trạng thái: 0" in text
    assert "Không có đoạn dữ liệu nào chuyển trạng thái lọc" in text
    assert before.totals["gps_filtered_km"] == pytest.approx(after.totals["gps_filtered_km"])


