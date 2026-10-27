from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QTableView, QVBoxLayout, QWidget

from core.models import AnalysisResult
from ui.dataframe_model import DataFrameModel


def build_daily_display(daily: pd.DataFrame) -> pd.DataFrame:
    """Giữ mẫu bảng cũ và chèn một dòng tổng sau mỗi file nguồn."""
    columns = [
        "date",
        "device_id",
        "device_original_km",
        "gps_filtered_km",
        "warning_count",
        "warnings",
        "record_count",
    ]
    if daily.empty:
        return pd.DataFrame(columns=columns)
    if "source_file" not in daily.columns:
        return daily[columns].copy()

    rows: list[dict[str, object]] = []
    for source_file, group in daily.groupby("source_file", sort=True, dropna=False):
        rows.extend(group[columns].to_dict("records"))
        total: dict[str, object] = {
            "date": "TỔNG FILE",
            "device_id": f"TỔNG FILE: {source_file}",
            "warnings": "Tổng km và cảnh báo của file",
        }
        for column in (
            "device_original_km",
            "gps_filtered_km",
            "warning_count",
            "record_count",
        ):
            values = pd.to_numeric(group[column], errors="coerce")
            total[column] = values.sum(min_count=1)
        rows.append(total)
    return pd.DataFrame(rows, columns=columns)


class KpiCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("kpiCard")
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setObjectName("kpiTitle")
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value)


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        heading = QLabel("Tổng quan phân tích")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        grid = QGridLayout()
        labels = [
            ("days", "Tổng số ngày"),
            ("records", "Tổng số bản ghi"),
            ("device_original_km", "Km thiết bị báo"),
            ("gps_filtered_km", "Km GPS sau lọc"),
            ("events", "Bản ghi có cảnh báo"),
        ]
        self.cards = {}
        for i, (key, label) in enumerate(labels):
            card = KpiCard(label)
            self.cards[key] = card
            grid.addWidget(card, i // 4, i % 4)
        layout.addLayout(grid)
        layout.addWidget(QLabel("Tổng hợp theo ngày"))
        self.table = QTableView()
        self.model = DataFrameModel()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table, 1)

    def set_result(self, result: AnalysisResult) -> None:
        totals = result.totals
        self.cards["records"].setToolTip("Tổng bản ghi nguồn, gồm duplicate và bản ghi bị loại; bảng ngày dùng cùng định nghĩa.")
        self.cards["events"].setToolTip(
            f"Valid: {totals.get('valid_records', 0):,.0f}; duplicate: {totals.get('duplicate_records', 0):,.0f}; "
            f"excluded: {totals.get('excluded_records', 0):,.0f}; nhóm sự kiện: {totals.get('unique_warning_events', 0):,.0f}. "
            "Các nhóm thống kê có thể giao nhau."
        )
        self.cards["device_original_km"].setToolTip(
            f"Tổng toàn kỳ; km chưa phân bổ ngày: {totals.get('unallocated_device_km') or 0:,.3f}. Xem báo cáo đối soát."
        )
        for key, card in self.cards.items():
            value = totals[key]
            if value is None:
                text = "N/A"
            elif key in {"days", "records", "events"}:
                text = f"{int(value):,}"
            else:
                text = f"{float(value):,.3f} km"
            card.value.setText(text)
        source_daily = result.file_daily if not result.file_daily.empty else result.daily
        self.daily_display = build_daily_display(source_daily)
        display = self.daily_display.rename(
            columns={
                "date": "Ngày",
                "device_id": "Thiết bị",
                "device_original_km": "Km thiết bị",
                "gps_filtered_km": "Km GPS lọc",
                "warning_count": "Cảnh báo",
                "warnings": "Chi tiết cảnh báo",
                "record_count": "Số bản ghi",
            }
        )
        self.model.set_frame(display)
        self.table.resizeColumnsToContents()

