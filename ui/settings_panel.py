from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.settings import FilterSettings


class SettingsPage(QWidget):
    recalculate_requested = Signal(object)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Cấu hình bộ lọc")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Conservative", "Balanced", "Aggressive"])
        self.max_speed = QDoubleSpinBox()
        self.max_speed.setRange(20, 500)
        self.max_speed.setValue(120)
        self.max_speed.setSuffix(" km/h")
        self.stop_speed = QDoubleSpinBox()
        self.stop_speed.setRange(0, 30)
        self.stop_speed.setValue(3)
        self.stop_speed.setSuffix(" km/h")
        self.stop_radius = QDoubleSpinBox()
        self.stop_radius.setRange(1, 1000)
        self.stop_radius.setValue(30)
        self.stop_radius.setSuffix(" m")
        self.gap = QSpinBox()
        self.gap.setRange(1, 86400)
        self.gap.setValue(120)
        self.gap.setSuffix(" giây")
        form.addRow("Chế độ:", self.mode)
        form.addRow("Tốc độ GPS tối đa:", self.max_speed)
        form.addRow("Ngưỡng xe dừng:", self.stop_speed)
        form.addRow("Bán kính dừng:", self.stop_radius)
        form.addRow("Khoảng mất GPS:", self.gap)
        layout.addLayout(form)
        note = QLabel(
            "Conservative chỉ loại điểm có bằng chứng mạnh. Balanced/Aggressive cũng loại "
            "các teleport đơn lẻ. Mỗi lần áp dụng sẽ phân tích lại toàn bộ dữ liệu."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        button = QPushButton("Lưu cấu hình")
        button.clicked.connect(lambda: self.recalculate_requested.emit(self.values()))
        layout.addWidget(button)
        layout.addStretch()

    def values(self) -> FilterSettings:
        return FilterSettings(
            max_plausible_speed_kmh=self.max_speed.value(),
            stop_speed_kmh=self.stop_speed.value(),
            stop_radius_meters=self.stop_radius.value(),
            max_gps_gap_seconds=self.gap.value(),
            mode=self.mode.currentText(),
        )
