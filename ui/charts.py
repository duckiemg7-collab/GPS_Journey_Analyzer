from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.models import AnalysisResult


class ChartsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.result: AnalysisResult | None = None
        layout = QVBoxLayout(self)
        title = QLabel("Biểu đồ hành trình")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Biểu đồ:"))
        self.kind = QComboBox()
        self.kind.addItems(["Km theo ngày", "Vận tốc", "Đường đi GPS"])
        self.kind.currentTextChanged.connect(self.redraw)
        controls.addWidget(self.kind)
        controls.addWidget(QLabel("Ngày:"))
        self.day = QComboBox()
        self.day.currentTextChanged.connect(self.redraw)
        controls.addWidget(self.day)
        controls.addStretch()
        layout.addLayout(controls)
        self.figure = Figure(figsize=(10, 6), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas, 1)
        self.canvas.mpl_connect("button_press_event", self._point_info)
        self._plotted = pd.DataFrame()

    def set_result(self, result: AnalysisResult):
        self.result = result
        self.day.blockSignals(True)
        self.day.clear()
        self.day.addItem("Tất cả")
        self.day.addItems(sorted(result.details["timestamp"].dropna().dt.strftime("%d/%m/%Y").unique()))
        self.day.blockSignals(False)
        self.redraw()

    def _selected(self) -> pd.DataFrame:
        if not self.result:
            return pd.DataFrame()
        data = self.result.details
        day = self.day.currentText()
        if day and day != "Tất cả":
            data = data[data["timestamp"].dt.strftime("%d/%m/%Y") == day]
        return data

    def redraw(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        if not self.result:
            ax.text(0.5, 0.5, "Chưa có dữ liệu", ha="center", va="center")
            self.canvas.draw_idle()
            return
        kind = self.kind.currentText()
        data = self._selected()
        self._plotted = data
        if kind == "Km theo ngày":
            daily = self.result.daily[self.result.daily["date"].notna()].copy()
            x = np.arange(len(daily))
            width = 0.36
            ax.bar(x - width / 2, daily["device_original_km"], width, label="Thiết bị", color="#2F6B9A")
            ax.bar(x + width / 2, daily["gps_filtered_km"], width, label="GPS lọc", color="#2E8B57")
            ax.set_xticks(x, [pd.Timestamp(d).strftime("%d/%m") for d in daily["date"]])
            ax.set_ylabel("km")
            ax.set_title("So sánh quãng đường theo ngày")
            ax.legend()
        elif kind == "Vận tốc":
            ax.plot(data["timestamp"], data["device_speed_kmh"], label="Thiết bị", color="#2F6B9A", lw=1)
            ax.plot(data["timestamp"], data["gps_speed_kmh"], label="GPS suy ra", color="#2E8B57", lw=0.8)
            bad = data[data["algorithm_status"] != "VALID"]
            ax.scatter(bad["timestamp"], bad["gps_speed_kmh"], color="#C0392B", s=18, label="Bất thường")
            ax.set_ylabel("km/h")
            ax.set_title("Vận tốc theo thời gian")
            ax.legend()
        else:
            valid = data[~data["exclude_from_gps"]]
            suspect = data[data["algorithm_status"].isin(["SUSPECTED_NOISE", "GPS_DRIFT"])]
            confirmed = data[data["algorithm_status"] == "CONFIRMED_OUTLIER"]
            ax.plot(valid["longitude"], valid["latitude"], color="#2E8B57", lw=1, label="Hợp lệ")
            ax.scatter(suspect["longitude"], suspect["latitude"], color="#F39C12", s=18, label="Nghi nhiễu")
            ax.scatter(confirmed["longitude"], confirmed["latitude"], color="#C0392B", s=22, label="Xác nhận lỗi")
            gaps = data[data["algorithm_status"] == "GPS_GAP"]
            ax.scatter(gaps["longitude"], gaps["latitude"], facecolors="none", edgecolors="#7E57C2", s=25, label="Mất GPS")
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.set_title("Tuyến tọa độ (không phải bản đồ địa lý)")
            ax.legend()
        ax.grid(True, alpha=0.2)
        self.canvas.draw_idle()

    def _point_info(self, event):
        if event.xdata is None or event.ydata is None or self._plotted.empty:
            return
        if self.kind.currentText() != "Đường đi GPS":
            return
        data = self._plotted.dropna(subset=["latitude", "longitude"])
        if data.empty:
            return
        scale = max(data["longitude"].max() - data["longitude"].min(), 1e-6)
        score = ((data["longitude"] - event.xdata) / scale) ** 2 + ((data["latitude"] - event.ydata) / scale) ** 2
        row = data.loc[score.idxmin()]
        self.parentWidget().window().statusBar().showMessage(
            f"{row['timestamp']:%d/%m/%Y %H:%M:%S} | {row['device_speed_kmh']:.1f} km/h | "
            f"{row['algorithm_status']} | {row['warning_reason']}", 12000
        )

