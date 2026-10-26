"""Verify generated V1.2 evidence and refresh presentation-only warning labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pandas as pd
from openpyxl import load_workbook
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.daily_aggregator import warning_mask

ROOT = Path("output/audit_v12")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def refresh_labels():
    for name in ("after_daily.csv", "comparison_daily.csv"):
        path = ROOT / name
        data = pd.read_csv(path, dtype={"device_id": str})
        for column in data.select_dtypes(include=["object", "string"]):
            data[column] = data[column].str.replace(r"\bVALID: ", "DEVICE_NEED_REVIEW: ", regex=True)
        if "change_reason" in data:
            data["change_reason"] = data.change_reason.str.replace("nan: ", "Point excluded; see changed_segments: ", regex=False)
        data.to_csv(path, index=False, encoding="utf-8-sig")
    path = ROOT / "changed_segments.csv"
    data = pd.read_csv(path, dtype={"device_id": str})
    missing = data.gps_segment_reason.isna()
    data.loc[missing, "gps_segment_reason"] = "Point excluded as " + data.loc[missing, "algorithm_status_after"] + "; see raw warning_reason"
    data.to_csv(path, index=False, encoding="utf-8-sig")

    report = ROOT / "GPS_Journey_Analyzer_V1.2_Audit.xlsx"
    revised = ROOT / "_verified_report.xlsx"
    with ZipFile(report) as src, ZipFile(revised, "w") as dst:
        for info in src.infolist():
            if info.filename in {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet8.xml"}:
                text = src.read(info.filename).decode("utf-8")
                text = re.sub(r"\bVALID: ", "DEVICE_NEED_REVIEW: ", text)
                text = text.replace("nan: ", "Point excluded; see changed_segments: ")
                dst.writestr(info, text.encode("utf-8"))
            elif info.filename == "xl/worksheets/sheet12.xml":
                root = ET.fromstring(src.read(info.filename))
                for row in root.findall(f".//{{{NS}}}sheetData/{{{NS}}}row")[1:]:
                    cells = list(row)
                    if len(cells) < 16:
                        continue
                    reason = cells[13]
                    reason_text = "".join(reason.itertext())
                    if not reason_text:
                        reason.set("t", "inlineStr")
                        for child in list(reason):
                            reason.remove(child)
                        inline = ET.SubElement(reason, f"{{{NS}}}is")
                        ET.SubElement(inline, f"{{{NS}}}t").text = "Point excluded as " + "".join(cells[15].itertext()) + "; see raw warning_reason"
                dst.writestr(info, ET.tostring(root, encoding="utf-8"))
            else:
                with src.open(info) as reader, dst.open(info, "w", force_zip64=True) as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
    revised.replace(report)


def verify():
    hashes = json.loads((ROOT / "source_hashes.json").read_text(encoding="utf-8"))
    assert all(hashlib.sha256((Path("file_sample_excel") / name).read_bytes()).hexdigest() == expected for name, expected in hashes.items())
    comparison = pd.read_csv(ROOT / "comparison_daily.csv", dtype={"device_id": str})
    assert not comparison.gps_filtered_km_before.isna().any()
    daily = pd.read_csv(ROOT / "after_daily.csv", dtype={"device_id": str})
    details = pd.read_pickle(ROOT / "after_details.pkl")
    assert len(comparison) == len(daily)
    assert daily.record_count.sum() == len(details)
    assert daily.warning_count.sum() == warning_mask(details).sum()
    period = pd.read_csv(ROOT / "period_reconciliation.csv", dtype={"device_id": str})
    assert period.counter_reconciliation_difference_km.abs().max() < 1e-7
    report = ROOT / "GPS_Journey_Analyzer_V1.2_Audit.xlsx"
    with ZipFile(report) as archive:
        assert archive.testzip() is None
    wb = load_workbook(report, read_only=True, data_only=False)
    assert len(wb.sheetnames) == 13
    assert wb["Chi tiết GPS"]["A1"].value == "detail_index"
    unverified = wb["Các đoạn GPS chưa xác minh"]
    first_rows = unverified.iter_rows(values_only=True)
    headers = next(first_rows)
    record = dict(zip(headers, next(first_rows)))
    assert record["actual_unverified_km"] == "Không đủ căn cứ"
    wb.close()
    print(json.dumps({"workbooks": len(hashes), "source_hashes_unchanged": True,
                      "raw_records": int(daily.record_count.sum()), "warning_records": int(daily.warning_count.sum()),
                      "device_day_rows": len(comparison), "sheets": 13,
                      "report_bytes": report.stat().st_size}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    refresh_labels()
    verify()
