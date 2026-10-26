from __future__ import annotations

from datetime import datetime
from copy import copy
from pathlib import Path
import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.cell import WriteOnlyCell

from config.settings import ALGORITHM_VERSION
from core.models import AnalysisResult


NAVY = "17324D"
BLUE = "2F6B9A"
LIGHT_BLUE = "DCEAF5"
GREEN = "2E8B57"
AMBER = "F4B942"
RED = "C0392B"
WHITE = "FFFFFF"
TEXT = "243746"


def _safe(value):
    if value is pd.NA or value is pd.NaT or (isinstance(value, (float, np.floating)) and np.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _write_dataframe(ws, frame: pd.DataFrame, start_row: int = 1) -> tuple[int, int]:
    for col, name in enumerate(frame.columns, 1):
        cell = ws.cell(start_row, col, str(name))
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(name="Arial", size=10, bold=True, color=WHITE)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r, row in enumerate(frame.itertuples(index=False, name=None), start_row + 1):
        for c, value in enumerate(row, 1):
            safe = _safe(value)
            ws.cell(r, c, "Không đủ căn cứ" if safe is None else safe)
    last_row = start_row + len(frame)
    last_col = len(frame.columns)
    if last_col:
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(last_col)}{max(start_row, last_row)}"
    return last_row, last_col


def _finish_sheet(ws, freeze: str = "A2", max_width: int = 42) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = freeze
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.tabColor = BLUE
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        sample = list(column_cells[:250])
        width = max((len(str(c.value)) for c in sample if c.value is not None), default=8) + 2
        ws.column_dimensions[letter].width = min(max(width, 10), max_width)
    for row in ws.iter_rows():
        for cell in row:
            font = copy(cell.font)
            font.name, font.sz = "Arial", 10
            cell.font = font
            alignment = copy(cell.alignment)
            alignment.vertical = "center"
            cell.alignment = alignment


def _format_detail(ws, headers: list[str], last_row: int) -> None:
    if last_row < 2:
        return
    for idx, name in enumerate(headers, 1):
        if name == "timestamp" or name.endswith("_timestamp"):
            for cell in ws.iter_cols(idx, idx, 2, last_row):
                cell[0].number_format = "dd/mm/yyyy hh:mm:ss"
        if name.endswith("_km") or name in {"raw_distance_km", "gps_filtered_segment_km"}:
            for cell in ws.iter_cols(idx, idx, 2, last_row):
                cell[0].number_format = "0.000"
        if name.endswith("_kmh"):
            for cell in ws.iter_cols(idx, idx, 2, last_row):
                cell[0].number_format = "0.0"


def reconciliation_tables(result: AnalysisResult) -> dict[str, pd.DataFrame]:
    evidence = result.counter_evidence
    segment_columns = [
        "segment_id", "device_id", "gps_segment_class", "gps_segment_reason",
        "start_timestamp", "end_timestamp", "start_latitude", "start_longitude",
        "end_latitude", "end_longitude", "start_source_file", "start_source_sheet",
        "start_source_row", "end_source_file", "end_source_sheet", "end_source_row",
        "gps_segment_start_index", "gps_segment_end_index", "gps_segment_seconds",
        "gps_segment_reference_km", "actual_unverified_km", "reference_kind",
    ]
    counter_columns = [
        "counter_edge_id", "device_id", "start_timestamp", "end_timestamp",
        "start_latitude", "start_longitude", "end_latitude", "end_longitude",
        "start_source_file", "start_source_row", "end_source_file", "end_source_row",
        "start_device_km", "end_device_km", "device_km_delta", "raw_distance_km",
        "delta_time_seconds", "gps_speed_kmh", "counter_speed_kmh", "device_suspected_km",
        "deducted_km", "confirmation_status", "evidence",
    ]
    segments = result.segments
    if segments.empty:
        unverified = pd.DataFrame(columns=segment_columns)
    else:
        unverified = segments.loc[segments.gps_segment_class.eq("UNVERIFIED")].reindex(columns=segment_columns)
    if evidence.empty:
        suspected = confirmed = pd.DataFrame(columns=counter_columns)
    else:
        suspected = evidence.loc[evidence.confirmation_status.eq("NEED_REVIEW")].reindex(columns=counter_columns)
        confirmed = evidence.loc[evidence.confirmation_status.eq("CONFIRMED")].reindex(columns=counter_columns)
    return {
        "Km thiết bị nghi cộng sai": suspected,
        "Km thiết bị cộng sai xác nhận": confirmed,
        "Các đoạn GPS chưa xác minh": unverified,
        "Đối soát toàn kỳ": result.reconciliation,
    }


def export_reconciliation_report(
    result: AnalysisResult, output_path: str | Path,
    comparison: pd.DataFrame | None = None, per_file: pd.DataFrame | None = None,
    extra_tables: dict[str, pd.DataFrame] | None = None,
) -> Path:
    """Stream the full sample audit without retaining millions of Excel cells."""
    path = Path(output_path).resolve()
    if path in {p.resolve() for p in result.files}:
        raise ValueError("Không được ghi đè file Excel nguồn")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook(write_only=True)
    detail_columns = [
        "device_id", "source_file", "source_sheet", "source_row", "timestamp", "latitude", "longitude",
        "device_status", "device_speed_kmh", "device_km", "device_km_delta", "raw_distance_km",
        "delta_time_seconds", "gps_speed_kmh", "gps_filtered_segment_km", "gps_unverified_segment_km",
        "gps_confirmed_outlier_segment_km", "confirmed_false_km", "device_anomaly_status",
        "algorithm_status", "exclude_from_gps", "warning_event_id", "warning_reason",
        "is_duplicate", "invalid_timestamp", "timestamp_conflict", "no_fix_coordinate", "signal_loss_observed",
        "gps_segment_start_index", "gps_segment_end_index", "gps_segment_class", "gps_segment_reason",
    ]
    tables = {
        "Tổng hợp theo ngày": result.daily,
        "Chi tiết GPS": result.details.reindex(columns=detail_columns).reset_index(names="detail_index"),
        "Các sự kiện nhiễu": result.events.reindex(columns=detail_columns).reset_index(names="detail_index"),
        **reconciliation_tables(result),
    }
    if comparison is not None:
        tables["So sánh trước sau"] = comparison
    if per_file is not None:
        tables["Tổng hợp theo file"] = per_file
    tables.update(extra_tables or {})
    log = [("Algorithm", ALGORITHM_VERSION), ("Settings", str(result.settings.to_dict()))]
    log += [("Definition", text) for text in [
        "gps_unverified_km: endpoint Haversine reference, NOT actual unknown mileage.",
        "gps_confirmed_outlier_km: removed RAW geometry, NOT additive to rebuilt route groups.",
        "Each canonical raw interval belongs to exactly one rebuilt segment span.",
        "Raw/valid/duplicate/excluded/warning are record counts. Excluded, duplicate and warning overlap.",
        "Unique warning event: consecutive same category/device/day warning records, time gap <=120s.",
        "unallocated_device_km: cross-day counter increase; endpoint day is only an audit bucket.",
        "Unknown actual_unverified_km is displayed as Không đủ căn cứ, never zero.",
        "No odometer subtraction is proven by GPS jumps alone; current candidates remain NEED_REVIEW.",
    ]]
    log += [("Source", str(p)) for p in result.files]
    log += [("Log", message) for message in result.logs]
    tables["Nhật ký thuật toán và cấu hình"] = pd.DataFrame(log, columns=["Mục", "Nội dung"])
    for name, frame in tables.items():
        ws = wb.create_sheet(name)
        ws.freeze_panes = "A2"
        ws.sheet_view.showGridLines = False
        for idx, column in enumerate(frame.columns, 1):
            ws.column_dimensions[get_column_letter(idx)].width = 23 if "timestamp" in column else 18
        headers = []
        for column in frame.columns:
            cell = WriteOnlyCell(ws, str(column))
            cell.fill = PatternFill("solid", fgColor=NAVY)
            cell.font = Font(name="Arial", bold=True, color=WHITE)
            headers.append(cell)
        ws.append(headers)
        for values in frame.itertuples(index=False, name=None):
            cells = []
            for column, value in zip(frame.columns, values):
                value = _safe(value)
                if value is None:
                    value = "Không đủ căn cứ"
                cell = WriteOnlyCell(ws, value)
                if "timestamp" in column or column == "date":
                    cell.number_format = "dd/mm/yyyy hh:mm:ss"
                elif column.endswith("_km") or column.endswith("_kmh"):
                    cell.number_format = "0.000"
                cells.append(cell)
            ws.append(cells)
        ws.auto_filter.ref = f"A1:{get_column_letter(max(1, len(frame.columns)))}{len(frame) + 1}"
    wb.save(path)
    return path


def export_report(result: AnalysisResult, output_path: str | Path) -> Path:
    path = Path(output_path).resolve()
    if path in {p.resolve() for p in result.files}:
        raise ValueError("Không được ghi đè file Excel nguồn")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"

    summary = result.daily[[
        "date", "device_id", "device_original_km", "gps_filtered_km",
        "device_corrected_km", "confirmed_false_km", "warning_count", "warnings", "record_count",
    ]].copy()
    summary.columns = [
        "Ngày",
        "Thiết bị",
        "Km gốc",
        "Km GPS lọc",
        "Km hiệu chỉnh",
        "Km sai xác nhận",
        "Số cảnh báo",
        "Cảnh báo",
        "Số bản ghi",
    ]
    ws = wb.create_sheet("Tổng hợp theo ngày")
    last_row, _ = _write_dataframe(ws, summary)
    total_row = last_row + 2
    ws.cell(total_row, 1, "TỔNG TOÀN KỲ")
    ws.cell(total_row, 1).font = Font(name="Arial", bold=True, color=WHITE)
    ws.cell(total_row, 1).fill = PatternFill("solid", fgColor=BLUE)
    for col in (3, 4, 5, 6, 7, 9):
        letter = get_column_letter(col)
        ws.cell(total_row, col, f"=SUM({letter}2:{letter}{last_row})")
        ws.cell(total_row, col).font = Font(name="Arial", bold=True)
        if col in (3, 4, 5, 6):
            ws.cell(total_row, col).number_format = "0.000"
    for row in range(2, last_row + 1):
        ws.cell(row, 1).number_format = "dd/mm/yyyy"
        for col in (3, 4, 5, 6):
            ws.cell(row, col).number_format = "0.000"
    ws.conditional_formatting.add(
        f"G2:G{last_row}",
        FormulaRule(formula=["G2>0"], fill=PatternFill("solid", fgColor="FFF1CC")),
    )
    _finish_sheet(ws)

    details = result.details.reset_index(names="detail_index")
    ws_detail = wb.create_sheet("Chi tiết GPS")
    detail_last, _ = _write_dataframe(ws_detail, details)
    _format_detail(ws_detail, list(details.columns), detail_last)
    _finish_sheet(ws_detail, "E2", 34)

    event_columns = [
        "timestamp",
        "device_id",
        "latitude",
        "longitude",
        "raw_distance_km",
        "delta_time_seconds",
        "gps_speed_kmh",
        "device_speed_kmh",
        "device_km",
        "device_km_delta",
        "confirmed_false_km",
        "event_type",
        "warning_reason",
        "algorithm_status",
        "source_file",
        "source_sheet",
        "source_row",
    ]
    event_columns = [c for c in event_columns if c in result.events.columns]
    ws_events = wb.create_sheet("Điểm GPS bất thường")
    event_last, _ = _write_dataframe(ws_events, result.events[event_columns])
    _format_detail(ws_events, event_columns, event_last)
    _finish_sheet(ws_events, "A2", 50)

    for name, frame in reconciliation_tables(result).items():
        audit_ws = wb.create_sheet(name)
        last, _ = _write_dataframe(audit_ws, frame)
        _format_detail(audit_ws, list(frame.columns), last)
        _finish_sheet(audit_ws, "A2", 45)

    comparison = result.daily[
        [
            "date",
            "device_id",
            "device_original_km",
            "gps_filtered_km",
            "device_corrected_km",
            "confirmed_false_km",
        ]
    ].copy()
    comparison["difference_device_vs_gps_km"] = (
        comparison["device_original_km"] - comparison["gps_filtered_km"]
    )
    ws_compare = wb.create_sheet("Đối chiếu km")
    comp_last, _ = _write_dataframe(ws_compare, comparison)
    _format_detail(ws_compare, list(comparison.columns), comp_last)
    _finish_sheet(ws_compare)

    ws_chart = wb.create_sheet("Biểu đồ và thống kê")
    ws_chart.sheet_view.showGridLines = False
    ws_chart["A2"] = "GPS Journey Analyzer"
    ws_chart["A2"].font = Font(name="Arial", size=16, bold=True, color=NAVY)
    ws_chart["A4"] = "Chỉ số"
    ws_chart["B4"] = "Giá trị"
    totals = result.totals
    metrics = [
        ("Tổng số ngày", totals["days"]),
        ("Tổng bản ghi", totals["records"]),
        ("Km thiết bị báo", totals["device_original_km"]),
        ("Km GPS sau lọc", totals["gps_filtered_km"]),
        ("Km thiết bị hiệu chỉnh", totals["device_corrected_km"]),
        ("Km sai xác nhận", totals["confirmed_false_km"]),
        ("Bản ghi có cảnh báo", totals["events"]),
        ("Nhóm sự kiện cảnh báo", totals.get("unique_warning_events")),
    ]
    for col in (1, 2):
        ws_chart.cell(4, col).fill = PatternFill("solid", fgColor=NAVY)
        ws_chart.cell(4, col).font = Font(name="Arial", bold=True, color=WHITE)
    for row, (label, value) in enumerate(metrics, 5):
        ws_chart.cell(row, 1, label)
        ws_chart.cell(row, 2, _safe(value))
        if "Km" in label:
            ws_chart.cell(row, 2).number_format = "0.000"
    chart_start = 15
    chart_data = result.daily[result.daily["date"].notna()].copy()
    chart_data["label"] = chart_data.apply(
        lambda r: f"{pd.Timestamp(r['date']).strftime('%d/%m')} {r['device_id']}", axis=1
    )
    chart_table = chart_data[
        ["label", "device_original_km", "gps_filtered_km", "device_corrected_km"]
    ]
    _write_dataframe(ws_chart, chart_table, chart_start)
    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    chart.title = "So sánh quãng đường theo ngày (km)"
    chart.y_axis.title = "km"
    chart.x_axis.title = "Ngày / thiết bị"
    chart.add_data(
        Reference(ws_chart, min_col=2, max_col=4, min_row=chart_start, max_row=chart_start + len(chart_table)),
        titles_from_data=True,
    )
    chart.set_categories(
        Reference(ws_chart, min_col=1, min_row=chart_start + 1, max_row=chart_start + len(chart_table))
    )
    chart.height = 9
    chart.width = 20
    ws_chart.add_chart(chart, "D4")
    _finish_sheet(ws_chart, "A1", 28)

    ws_log = wb.create_sheet("Nhật ký xử lý")
    log_rows = [
        ("Thời điểm xuất", datetime.now()),
        ("Phiên bản thuật toán", ALGORITHM_VERSION),
        ("Chế độ lọc", result.settings.mode),
        ("MAX_PLAUSIBLE_SPEED_KMH", result.settings.max_plausible_speed_kmh),
        ("STOP_SPEED_KMH", result.settings.stop_speed_kmh),
        ("STOP_RADIUS_METERS", result.settings.stop_radius_meters),
        ("MAX_GPS_GAP_SECONDS", result.settings.max_gps_gap_seconds),
        ("Giới hạn", "GPS lọc là độ dài tuyến nối điểm được chấp nhận, không phải quãng đường thực tuyệt đối."),
        ("Giới hạn", "Đoạn mất GPS không được tự nối; kết quả có thể thấp hơn thực tế."),
        ("Km chưa xác minh", "Chỉ là Haversine đường thẳng tham khảo; quãng đường thực chưa biết. Không cộng với GPS lọc."),
        ("GPS outlier loại", "Độ dài hình học thô đã loại; không cộng vào các nhóm quãng đường tái dựng."),
        ("Km chưa phân bổ", "Mức tăng công tơ qua ngày giữ riêng; tổng ngày + chưa phân bổ = tổng kỳ độc lập."),
        ("Thống kê", "Raw gồm mọi dòng; valid = không cảnh báo; duplicate và excluded có thể giao với warning. Sự kiện là nhóm cảnh báo liên tiếp cùng loại/xe/ngày, cách tối đa 120 giây."),
    ]
    for file in result.files:
        log_rows.append(("File nguồn", str(file)))
    for message in result.logs:
        log_rows.append(("Nhật ký", message))
    _write_dataframe(ws_log, pd.DataFrame(log_rows, columns=["Mục", "Nội dung"]))
    ws_log["B2"].number_format = "dd/mm/yyyy hh:mm:ss"
    _finish_sheet(ws_log, "A2", 100)

    wb.save(path)
    # Kiểm tra file có thể mở lại và đủ sheet sau khi ghi.
    check = load_workbook(path, read_only=True, data_only=False)
    expected = {
        "Tổng hợp theo ngày",
        "Chi tiết GPS",
        "Điểm GPS bất thường",
        "Đối chiếu km",
        "Biểu đồ và thống kê",
        "Nhật ký xử lý",
    }
    missing = expected.difference(check.sheetnames)
    check.close()
    if missing:
        raise RuntimeError(f"Báo cáo thiếu sheet: {sorted(missing)}")
    return path
