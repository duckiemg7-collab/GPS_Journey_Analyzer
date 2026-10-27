from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QLabel, QTableView, QVBoxLayout, QWidget

from core.display_labels import event_type_label, warning_status_label
from ui.dataframe_model import DataFrameModel


class NoiseAnalysisPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Phát hiện nhiễu GPS và đối chiếu km")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.summary = QLabel("Chưa có dữ liệu")
        layout.addWidget(self.summary)
        self.table = QTableView()
        self.model = DataFrameModel()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def set_data(self, events: pd.DataFrame) -> None:
        columns = [
            "timestamp", "device_id", "event_type", "algorithm_status", "raw_distance_km",
            "gps_speed_kmh", "device_km_delta", "confirmed_false_km", "warning_reason",
            "source_file", "source_row",
        ]
        columns = [c for c in columns if c in events.columns]
        shown = events[columns].copy()
        if "event_type" in shown:
            shown["event_type"] = shown["event_type"].map(event_type_label)
        if "algorithm_status" in shown:
            shown["algorithm_status"] = shown["algorithm_status"].map(warning_status_label)
        self.model.set_frame(shown)
        counts = events["algorithm_status"].value_counts() if not events.empty else pd.Series(dtype=int)
        self.summary.setText(
            " • ".join(f"{warning_status_label(k)}: {v:,}" for k, v in counts.items())
            or "Không có cảnh báo"
        )
        self.table.resizeColumnsToContents()

