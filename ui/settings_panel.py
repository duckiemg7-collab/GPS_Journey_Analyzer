from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
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
        self.mode.currentTextChanged.connect(self._refresh_effective)
        self.max_speed = QDoubleSpinBox()
        self.max_speed.setRange(20, 500)
        self.max_speed.setValue(120)
        self.max_speed.setSuffix(" km/h")
        self.max_speed.valueChanged.connect(self._refresh_effective)
        self.stop_speed = QDoubleSpinBox()
        self.stop_speed.setRange(0, 30)
        self.stop_speed.setValue(3)
        self.stop_speed.setSuffix(" km/h")
        self.stop_speed.valueChanged.connect(self._refresh_effective)
        self.stop_radius = QDoubleSpinBox()
        self.stop_radius.setRange(1, 1000)
        self.stop_radius.setValue(30)
        self.stop_radius.setSuffix(" m")
        self.stop_radius.valueChanged.connect(self._refresh_effective)
        self.gap = QSpinBox()
        self.gap.setRange(1, 86400)
        self.gap.setValue(120)
        self.gap.setSuffix(" giây")
        self.gap.valueChanged.connect(self._refresh_effective)
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
        self.effective_label = QLabel()
        self.effective_label.setWordWrap(True)
        layout.addWidget(self.effective_label)
        button = QPushButton("Lưu và áp dụng")
        button.clicked.connect(lambda: self.recalculate_requested.emit(self.values()))
        layout.addWidget(button)
        comparison_title = QLabel("Đối chiếu lần áp dụng gần nhất")
        comparison_title.setObjectName("pageTitle")
        layout.addWidget(comparison_title)
        self.comparison = QTextEdit()
        self.comparison.setReadOnly(True)
        self.comparison.setPlaceholderText("Chưa có lần áp dụng cấu hình nào để đối chiếu.")
        self.comparison.setMinimumHeight(220)
        layout.addWidget(self.comparison)
        layout.addStretch()
        self._refresh_effective()

    def values(self) -> FilterSettings:
        return FilterSettings(
            max_plausible_speed_kmh=self.max_speed.value(),
            stop_speed_kmh=self.stop_speed.value(),
            stop_radius_meters=self.stop_radius.value(),
            max_gps_gap_seconds=self.gap.value(),
            mode=self.mode.currentText(),
        )

    def _refresh_effective(self, _value=None) -> None:
        settings = self.values()
        effective = settings.effective()
        self.effective_label.setText(
            "Ngưỡng thực tế sẽ dùng: "
            f"tốc độ tối đa {effective.max_plausible_speed_kmh:g} km/h; "
            f"bán kính dừng {effective.stop_radius_meters:g} m; "
            f"ngưỡng dừng {effective.stop_speed_kmh:g} km/h; "
            f"khoảng mất GPS {effective.max_gps_gap_seconds} giây."
        )

    def show_comparison(self, text: str) -> None:
        self.comparison.setPlainText(text)
