from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def test_main_window_constructs():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "GPS Journey Analyzer"
    window.close()


def test_main_window_displays_reconciled_counts():
    from core.pipeline import analyze_records
    from tests.conftest import make_frame
    app = QApplication.instance() or QApplication([])
    row = ("2026-10-01 08:00:00", 10, 106, 0, 1)
    result = analyze_records(make_frame([row, row]), [])
    window = MainWindow()
    window._analysis_done(result)
    window.show()
    app.processEvents()
    assert window.dashboard.cards["records"].value.text() == "2"
    assert window.dashboard.cards["events"].value.text() == "1"
    assert result.daily.record_count.sum() == 2
    assert result.daily.warning_count.sum() == 1
    window.close()


def test_main_window_handles_unknown_date_bucket():
    import pandas as pd
    from core.pipeline import analyze_records
    from tests.conftest import make_frame
    app = QApplication.instance() or QApplication([])
    raw = make_frame([("2026-10-01 08:00:00", 10, 106, 0, 1), ("2026-10-01 08:01:00", 10, 106, 0, 2)])
    raw.loc[1, "timestamp"] = pd.NaT
    window = MainWindow()
    window._analysis_done(analyze_records(raw, []))
    window.show()
    app.processEvents()
    assert window.dashboard.cards["records"].value.text() == "2"
    window.close()
