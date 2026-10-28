from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config.settings import FilterSettings
from core.models import AnalysisResult
from core.pipeline import analyze_paths
from reports.excel_exporter import export_report
from ui.charts import ChartsPage
from ui.dashboard import DashboardPage, build_daily_display
from ui.dataframe_model import DataFrameModel
from ui.gps_detail import GpsDetailPage
from ui.noise_analysis import NoiseAnalysisPage
from ui.settings_panel import SettingsPage


def _result_filter_counts(result: AnalysisResult) -> dict[str, float | int]:
    details = result.details
    statuses = details["algorithm_status"]
    return {
        "gps_km": float(result.totals.get("gps_filtered_km") or 0.0),
        "accepted": int(details["gps_segment_class"].eq("TRUSTED").sum()),
        "suspected": int(statuses.isin(
            ["SUSPECTED_NOISE", "GPS_DRIFT", "CONFIRMED_OUTLIER"]
        ).sum()),
        "gaps": int(details["gps_segment_class"].eq("UNVERIFIED").sum()),
    }


def build_settings_comparison(before: AnalysisResult, after: AnalysisResult) -> str:
    """Build a traceable before/after summary using stable source-row keys."""
    old = _result_filter_counts(before)
    new = _result_filter_counts(after)
    keys = [
        column for column in ("source_file", "source_sheet", "source_row", "device_id", "timestamp")
        if column in before.details.columns and column in after.details.columns
    ]
    observed = ["algorithm_status", "gps_segment_class", "exclude_from_gps"]
    left = before.details[keys + observed].copy()
    right = after.details[keys + observed].copy()
    merged = left.merge(right, on=keys, how="outer", suffixes=("_old", "_new"), indicator=True)
    changed = merged["_merge"].ne("both")
    for column in observed:
        changed |= merged[f"{column}_old"].fillna("<missing>").ne(
            merged[f"{column}_new"].fillna("<missing>")
        )
    affected = merged.loc[changed]

    lines = [
        f"Cấu hình trước: {before.settings.describe()}",
        f"Ngưỡng thực trước: {before.settings.effective().describe()}",
        f"Cấu hình mới: {after.settings.describe()}",
        f"Ngưỡng thực mới: {after.settings.effective().describe()}",
        "",
        f"Km GPS trước/sau: {old['gps_km']:.3f} → {new['gps_km']:.3f} km",
        f"Số đoạn chấp nhận trước/sau: {old['accepted']} → {new['accepted']}",
        f"Số đoạn nghi nhiễu trước/sau: {old['suspected']} → {new['suspected']}",
        f"Số đoạn mất/chưa xác minh trước/sau: {old['gaps']} → {new['gaps']}",
        f"Số đoạn thay đổi trạng thái: {len(affected)}",
    ]
    if affected.empty:
        lines.extend(["", "Không có đoạn dữ liệu nào chuyển trạng thái lọc với cấu hình mới."])
    else:
        lines.extend(["", "Các đoạn bị ảnh hưởng:"])
        for _, row in affected.head(100).iterrows():
            identity = ", ".join(f"{key}={row[key]}" for key in keys)
            lines.append(
                f"- {identity}: {row.get('algorithm_status_old', '<missing>')} / "
                f"{row.get('gps_segment_class_old', '')} → "
                f"{row.get('algorithm_status_new', '<missing>')} / "
                f"{row.get('gps_segment_class_new', '')}"
            )
        if len(affected) > 100:
            lines.append(f"… và {len(affected) - 100} đoạn khác.")
    return "\n".join(lines)


class AnalysisWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: list[str], settings: FilterSettings):
        super().__init__()
        self.paths = paths
        self.settings = settings

    @Slot()
    def run(self):
        try:
            self.finished.emit(analyze_paths(self.paths, self.settings))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self, initial_paths: list[str] | None = None):
        super().__init__()
        self.setWindowTitle("GPS Journey Analyzer")
        self.resize(1500, 900)
        self.paths = initial_paths or []
        self.pending_settings = FilterSettings()
        self.selection_dirty = bool(self.paths)
        self.result: AnalysisResult | None = None
        self.thread: QThread | None = None
        self._queued_settings: FilterSettings | None = None
        self._active_settings: FilterSettings | None = None
        self._active_reason = "manual"
        self._comparison_base: AnalysisResult | None = None
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        side = QVBoxLayout(sidebar)
        brand = QLabel("GPS Journey\nAnalyzer")
        brand.setObjectName("brand")
        side.addWidget(brand)
        self.stack = QStackedWidget()
        self.dashboard = DashboardPage()
        self.files_page, self.files_list = self._files_page()
        self.daily_page, self.daily_model = self._table_page("Tổng hợp theo ngày")
        self.detail = GpsDetailPage()
        self.noise = NoiseAnalysisPage()
        self.charts = ChartsPage()
        self.settings = SettingsPage()
        self.logs_page, self.logs = self._logs_page()
        pages = [
            ("Dashboard", self.dashboard),
            ("Danh sách file", self.files_page),
            ("Tổng hợp theo ngày", self.daily_page),
            ("Chi tiết GPS", self.detail),
            ("Phát hiện nhiễu", self.noise),
            ("Biểu đồ hành trình", self.charts),
            ("Cấu hình bộ lọc", self.settings),
            ("Nhật ký xử lý", self.logs_page),
        ]
        for index, (label, page) in enumerate(pages):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.clicked.connect(lambda _=False, i=index: self.stack.setCurrentIndex(i))
            side.addWidget(button)
            self.stack.addWidget(page)
        side.addStretch()
        outer.addWidget(sidebar)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        toolbar = QHBoxLayout()
        add_files = QPushButton("Nhập file Excel")
        add_files.clicked.connect(self.choose_files)
        add_folder = QPushButton("Nhập thư mục")
        add_folder.clicked.connect(self.choose_folder)
        clear_selection = QPushButton("Bỏ chọn")
        clear_selection.clicked.connect(self.clear_selection)
        self.analyze_button = QPushButton("Phân tích dữ liệu")
        self.analyze_button.setObjectName("analyzeButton")
        self.analyze_button.clicked.connect(lambda: self.start_analysis(self.pending_settings))
        self.analyze_button.setEnabled(bool(self.paths))
        export = QPushButton("Xuất Excel")
        export.clicked.connect(self.export)
        self.export_button = export
        self.export_button.setEnabled(False)
        toolbar.addWidget(add_files)
        toolbar.addWidget(add_folder)
        toolbar.addWidget(clear_selection)
        toolbar.addWidget(self.analyze_button)
        toolbar.addWidget(export)
        toolbar.addStretch()
        self.selection_label = QLabel("Chưa chọn file")
        self.selection_label.setObjectName("selectionLabel")
        toolbar.addWidget(self.selection_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(260)
        toolbar.addWidget(self.progress)
        content_layout.addLayout(toolbar)
        content_layout.addWidget(self.stack, 1)
        outer.addWidget(content, 1)
        self.settings.recalculate_requested.connect(self._settings_changed)
        self.statusBar().showMessage("Sẵn sàng")
        self._refresh_selection(mark_dirty=bool(self.paths))

    def _files_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Danh sách file đã nhập")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        widget = QListWidget()
        layout.addWidget(widget)
        hint = QLabel("Chọn file/thư mục mới sẽ thay thế lựa chọn hiện tại. Bấm Phân tích dữ liệu để bắt đầu.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page, widget

    def _table_page(self, title_text: str):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(title_text)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        table = QTableView()
        model = DataFrameModel()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        layout.addWidget(table)
        page.table = table
        return page, model

    def _logs_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Nhật ký xử lý")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        text = QTextEdit()
        text.setReadOnly(True)
        layout.addWidget(text)
        return page, text

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #F5F7FA; color: #243746; font-family: 'Segoe UI'; font-size: 10pt; }
            #sidebar { background: #17324D; min-width: 215px; max-width: 215px; }
            #brand { background: transparent; color: white; font-size: 19pt; font-weight: 700; padding: 24px 14px; }
            #navButton { color: #DCEAF5; background: transparent; border: 0; text-align: left; padding: 11px 16px; }
            #navButton:hover { background: #264E70; color: white; }
            QPushButton { background: #2F6B9A; color: white; border: 0; border-radius: 5px; padding: 8px 14px; }
            QPushButton:hover { background: #245577; }
            #analyzeButton { background: #2E8B57; font-weight: 700; }
            #analyzeButton:hover { background: #246B45; }
            #selectionLabel { color: #607487; padding: 0 8px; }
            #pageTitle { font-size: 18pt; font-weight: 650; color: #17324D; padding: 5px 0 10px 0; }
            #kpiCard { background: white; border: 1px solid #DDE4EA; border-radius: 8px; padding: 8px; }
            #kpiTitle { color: #607487; font-size: 9pt; }
            #kpiValue { color: #17324D; font-size: 17pt; font-weight: 700; }
            QTableView { background: white; alternate-background-color: #F3F7FA; border: 1px solid #DDE4EA; gridline-color: #E8EDF1; }
            QHeaderView::section { background: #17324D; color: white; padding: 7px; border: 0; }
            QProgressBar { border: 1px solid #CBD6DF; border-radius: 5px; text-align: center; background: white; }
            QProgressBar::chunk { background: #2E8B57; border-radius: 4px; }
            QComboBox, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #CBD6DF; border-radius: 4px; padding: 6px; }
            """
        )

    @Slot()
    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file GPS", "", "Excel (*.xlsx *.xlsm)")
        if files:
            self.paths = files
            self._refresh_selection(mark_dirty=True)

    @Slot()
    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục Excel")
        if folder:
            self.paths = [folder]
            self._refresh_selection(mark_dirty=True)

    @Slot()
    def clear_selection(self):
        self.paths = []
        self._refresh_selection(mark_dirty=True)
        self.statusBar().showMessage("Đã bỏ chọn dữ liệu")

    def _refresh_selection(self, mark_dirty: bool = True):
        if mark_dirty:
            self.selection_dirty = bool(self.paths)
        self.files_list.clear()
        self.files_list.addItems(self.paths)
        if not self.paths:
            self.selection_label.setText("Chưa chọn file")
            self.analyze_button.setEnabled(False)
        elif len(self.paths) == 1:
            state = "(chưa phân tích)" if self.selection_dirty else "(đã phân tích)"
            self.selection_label.setText(f"Đang chọn: {Path(self.paths[0]).name} {state}")
            self.analyze_button.setEnabled(not self._analysis_running())
        else:
            state = "(chưa phân tích)" if self.selection_dirty else "(đã phân tích)"
            self.selection_label.setText(f"Đang chọn: {len(self.paths)} file {state}")
            self.analyze_button.setEnabled(not self._analysis_running())
        if mark_dirty or not self.paths:
            self.export_button.setEnabled(False)

    @Slot(object)
    def _settings_changed(self, settings: FilterSettings):
        self.pending_settings = settings
        if self._analysis_running():
            # Latest value wins.  Returning to the active configuration also
            # cancels an older queued request.
            self._queued_settings = None if settings == self._active_settings else settings
            self.statusBar().showMessage(
                "Đang phân tích; đã xếp hàng cấu hình mới nhất để áp dụng tiếp theo."
            )
            return
        if self.result is not None and self.paths:
            self.start_analysis(settings, reason="settings", comparison_base=self.result)
            return
        self.statusBar().showMessage(
            "Đã lưu cấu hình cho lần phân tích tiếp theo (chưa có dữ liệu để chạy lại).",
            8000,
        )

    def _analysis_running(self) -> bool:
        """Kiểm tra thread mà không giữ tham chiếu Qt đã bị giải phóng."""
        if self.thread is None:
            return False
        try:
            return bool(self.thread.isRunning())
        except RuntimeError:
            self.thread = None
            return False

    @Slot(object)
    def start_analysis(
        self,
        settings: FilterSettings,
        *,
        reason: str = "manual",
        comparison_base: AnalysisResult | None = None,
    ):
        if not self.paths:
            QMessageBox.information(self, "Chưa có dữ liệu", "Hãy chọn file hoặc thư mục Excel trước.")
            return
        if self._analysis_running():
            if settings != self._active_settings:
                self._queued_settings = settings
            self.statusBar().showMessage("Đang phân tích; chỉ cấu hình mới nhất sẽ được chạy tiếp.", 5000)
            return
        self._active_settings = settings
        self._active_reason = reason
        self._comparison_base = comparison_base
        self.progress.setRange(0, 0)
        self.analyze_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.statusBar().showMessage(
            "Đang áp dụng bộ lọc mới…" if reason == "settings"
            else "Đang đọc và phân tích dữ liệu…"
        )
        self.thread = QThread(self)
        worker = AnalysisWorker(self.paths, settings)
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.finished.connect(self._analysis_done)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(self.thread.quit)
        worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(worker.deleteLater)
        self.thread.finished.connect(self._analysis_thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self._worker = worker
        self.thread.start()

    @Slot(object)
    def _analysis_done(self, result: AnalysisResult):
        if self._queued_settings is not None and self._queued_settings != result.settings:
            self.statusBar().showMessage("Đã bỏ qua kết quả cũ; đang chờ áp dụng cấu hình mới nhất…")
            return
        comparison_base = self._comparison_base
        self.result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.dashboard.set_result(result)
        self.detail.set_data(result.details)
        self.noise.set_data(result.events)
        self.charts.set_result(result)
        source_daily = result.file_daily if not result.file_daily.empty else result.daily
        self.daily_model.set_frame(build_daily_display(source_daily).rename(
            columns={
                "date": "Ngày",
                "device_id": "Thiết bị",
                "device_original_km": "Km thiết bị",
                "gps_filtered_km": "Km GPS lọc",
                "warning_count": "Cảnh báo",
                "warnings": "Chi tiết cảnh báo",
                "record_count": "Số bản ghi",
            }
        ))
        self.daily_page.table.resizeColumnsToContents()
        self.paths = [str(p) for p in result.files]
        self.selection_dirty = False
        self._refresh_selection(mark_dirty=False)
        self.export_button.setEnabled(True)
        if self._active_reason == "settings" and comparison_base is not None:
            comparison = build_settings_comparison(comparison_base, result)
            self.settings.show_comparison(comparison)
            result.logs.append("Đối chiếu cấu hình:\n" + comparison)
        self.logs.setPlainText("\n".join(result.logs))
        self.statusBar().showMessage(
            f"Hoàn tất: {len(result.details):,} bản ghi, {len(result.events):,} bản ghi có cảnh báo"
        )

    @Slot(str)
    def _analysis_failed(self, message: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.analyze_button.setEnabled(bool(self.paths))
        if self._active_reason == "settings" and self.result is not None:
            self.settings.show_comparison(
                "Áp dụng cấu hình mới thất bại. Kết quả đang hiển thị vẫn dùng cấu hình cũ.\n"
                f"Lỗi: {message}"
            )
            self.export_button.setEnabled(True)
            self.statusBar().showMessage("Không áp dụng được cấu hình mới; đang giữ kết quả cũ.")
        else:
            self.statusBar().showMessage("Phân tích thất bại")
        QMessageBox.critical(self, "Lỗi phân tích", message)

    @Slot()
    def _analysis_thread_finished(self):
        self.thread = None
        queued = self._queued_settings
        self._queued_settings = None
        self._active_settings = None
        self._comparison_base = None
        if queued is not None and self.paths:
            self.start_analysis(
                queued,
                reason="settings",
                comparison_base=self.result,
            )
            return
        if self.paths:
            self.analyze_button.setEnabled(True)

    @Slot()
    def export(self):
        if not self.result:
            QMessageBox.information(self, "Chưa có kết quả", "Hãy phân tích dữ liệu trước khi xuất.")
            return
        default = str(Path.cwd() / "output" / "GPS_Journey_Analyzer_Report.xlsx")
        target, _ = QFileDialog.getSaveFileName(self, "Xuất báo cáo", default, "Excel (*.xlsx)")
        if not target:
            return
        try:
            path = export_report(self.result, target)
            self.statusBar().showMessage(f"Đã xuất: {path}", 15000)
            QMessageBox.information(self, "Xuất thành công", f"Đã tạo báo cáo:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi xuất Excel", str(exc))
