from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTableView, QVBoxLayout, QWidget

from core.display_labels import warning_status_label
from ui.dataframe_model import DataFrameModel


class GpsDetailPage(QWidget):
    def __init__(self):
        super().__init__()
        self.details = pd.DataFrame()
        layout = QVBoxLayout(self)
        title = QLabel("Chi tiết tọa độ GPS")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Ngày:"))
        self.day_combo = QComboBox()
        self.day_combo.currentTextChanged.connect(self._filter)
        controls.addWidget(self.day_combo)
        controls.addStretch()
        self.note = QLabel("")
        controls.addWidget(self.note)
        layout.addLayout(controls)
        self.table = QTableView()
        self.model = DataFrameModel()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def set_data(self, details: pd.DataFrame) -> None:
        self.details = details
        self.day_combo.blockSignals(True)
        self.day_combo.clear()
        self.day_combo.addItem("Tất cả")
        days = sorted(details["timestamp"].dropna().dt.strftime("%d/%m/%Y").unique())
        self.day_combo.addItems(days)
        self.day_combo.blockSignals(False)
        self._filter()

    def _filter(self):
        if self.details.empty:
            self.model.set_frame(pd.DataFrame())
            return
        day = self.day_combo.currentText()
        frame = self.details
        if day and day != "Tất cả":
            frame = frame[frame["timestamp"].dt.strftime("%d/%m/%Y") == day]
        columns = [
            "timestamp", "device_id", "latitude", "longitude", "device_speed_kmh",
            "gps_speed_kmh", "device_km", "raw_distance_km", "gps_filtered_segment_km",
            "algorithm_status", "warning_reason", "source_file", "source_row",
        ]
        columns = [c for c in columns if c in frame.columns]
        shown = frame[columns].head(10000).copy()
        if "algorithm_status" in shown:
            shown["algorithm_status"] = shown["algorithm_status"].map(warning_status_label)
        self.model.set_frame(shown)
        self.note.setText(f"Hiển thị {len(shown):,}/{len(frame):,} dòng")
        self.table.resizeColumnsToContents()

