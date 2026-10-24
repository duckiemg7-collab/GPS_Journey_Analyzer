from __future__ import annotations

import math

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont


class DataFrameModel(QAbstractTableModel):
    def __init__(self, frame: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._frame = frame if frame is not None else pd.DataFrame()

    def set_frame(self, frame: pd.DataFrame) -> None:
        self.beginResetModel()
        self._frame = frame.reset_index(drop=True)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._frame.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self._frame.iat[index.row(), index.column()]
        column = str(self._frame.columns[index.column()])
        row_values = self._frame.iloc[index.row()]
        is_total_row = any(str(item).startswith("TỔNG FILE") for item in row_values)
        if role == Qt.DisplayRole:
            if pd.isna(value):
                return "N/A"
            if isinstance(value, pd.Timestamp):
                return value.strftime("%d/%m/%Y %H:%M:%S")
            if isinstance(value, float):
                return f"{value:,.3f}"
            return str(value)
        if role == Qt.TextAlignmentRole:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        if role == Qt.BackgroundRole and is_total_row:
            return QColor("#2F6B9A")
        if role == Qt.ForegroundRole and is_total_row:
            return QColor("#FFFFFF")
        if role == Qt.FontRole and is_total_row:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.BackgroundRole and column == "algorithm_status":
            colors = {
                "CONFIRMED_OUTLIER": "#FADBD8",
                "SUSPECTED_NOISE": "#FDEBD0",
                "GPS_GAP": "#E8DAEF",
                "GPS_DRIFT": "#FCF3CF",
                "INVALID_COORDINATE": "#F5B7B1",
                "DUPLICATE": "#D5DBDB",
                "NEED_REVIEW": "#F9E79F",
            }
            if str(value) in colors:
                return QColor(colors[str(value)])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._frame.columns[section])
        return str(section + 1)

