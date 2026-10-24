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
