"""Reproducible local audit; source workbooks are read-only. Run from repo root."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from config.settings import FilterSettings
from core.excel_reader import discover_excel_files, read_excel_files
from core.gps_validator import validate_and_sort
from core.gps_filter import detect_and_filter
from core.daily_aggregator import aggregate_daily
from core.pipeline import analyze_records
from core.models import AnalysisResult
from core.daily_aggregator import warning_mask
from core.reconciliation import segment_view, counter_evidence_view, period_reconciliation, validate_reconciliation
from reports.excel_exporter import export_reconciliation_report
import numpy as np

ROOT = Path("output/audit_v12")


def baseline():
    ROOT.mkdir(parents=True, exist_ok=True)
    if any(ROOT.glob("*.before.pkl")):
        raise FileExistsError("Baseline already exists; refusing to overwrite pre-fix evidence")
    hashes = {}
    for path in discover_excel_files(["file_sample_excel"]):
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        raw, _, _ = read_excel_files([path])
        raw.to_pickle(ROOT / f"{path.stem}.raw.pkl")
        details = detect_and_filter(validate_and_sort(raw), FilterSettings())
        details.to_pickle(ROOT / f"{path.stem}.before.pkl")
        aggregate_daily(details).to_csv(ROOT / f"{path.stem}.before.csv", index=False)
        print(f"BASELINE {path.name}: {len(details)}", flush=True)
    (ROOT / "source_hashes.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")


def after(reuse_details=False):
    hashes = json.loads((ROOT / "source_hashes.json").read_text(encoding="utf-8"))
    files = discover_excel_files(["file_sample_excel"])
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name] for p in files)
    if reuse_details:
        details = pd.read_pickle(ROOT / "after_details.pkl")
        daily = aggregate_daily(details)
        periods = period_reconciliation(details, daily)
        segments = segment_view(details)
        validate_reconciliation(details, segments, periods)
        result = AnalysisResult(details, daily, details.loc[warning_mask(details)], files, FilterSettings(),
                                ["Full sample audit, cached final details; source SHA256 verified"],
                                aggregate_daily(details, by_source_file=True), segments, counter_evidence_view(details), periods)
    else:
        sources = [pd.read_pickle(ROOT / f"{p.stem}.raw.pkl") for p in files]
        raw = pd.concat(sources, ignore_index=True)
        raw["input_order"] = range(len(raw))
        print(f"ANALYZE {len(files)} files / {len(raw)} records", flush=True)
        result = analyze_records(raw, files)
    result.details.to_pickle(ROOT / "after_details.pkl")
    result.daily.to_csv(ROOT / "after_daily.csv", index=False)
    result.reconciliation.to_csv(ROOT / "period_reconciliation.csv", index=False)
    print("AFTER", result.totals, flush=True)
    before_daily = pd.concat([pd.read_csv(ROOT / f"{p.stem}.before.csv", dtype={"device_id": str}) for p in files], ignore_index=True)
    before_daily["date"] = pd.to_datetime(before_daily.date).dt.date
    columns = ["date", "device_id", "gps_filtered_km", "confirmed_false_km", "device_corrected_km"]
    comparison = result.daily.merge(before_daily[columns], on=["device_id", "date"], suffixes=("_after", "_before"), validate="one_to_one")
    changes = []
    for path in files:
        before = pd.read_pickle(ROOT / f"{path.stem}.before.pkl")
        current = result.details[result.details.source_file.eq(path.name)].copy()
        current = current.merge(before[["source_row", "source_sheet", "gps_filtered_segment_km", "algorithm_status", "raw_distance_km"]], on=["source_row", "source_sheet"], suffixes=("_after", "_before"), validate="one_to_one")
        current["gps_change_km"] = current.gps_filtered_segment_km_after - current.gps_filtered_segment_km_before
        changed = current.loc[current.gps_change_km.abs() > 1e-10].copy()
        missing_reason = changed.gps_segment_reason.eq("") | changed.gps_segment_reason.isna()
        changed.loc[missing_reason, "gps_segment_reason"] = "Point excluded as " + changed.loc[missing_reason, "algorithm_status_after"] + "; see raw warning_reason"
        changes.append(changed)
    changes = pd.concat(changes, ignore_index=True)
    changes["date"] = changes.timestamp.dt.date
    reasons = changes.groupby(["device_id", "date"]).apply(
        lambda g: "; ".join(f"{reason}: {values.gps_change_km.sum():+.6f} km ({len(values)} endpoints)" for reason, values in g.groupby("gps_segment_reason", dropna=False)), include_groups=False
    ).rename("change_reason").reset_index()
    comparison = comparison.merge(reasons, on=["device_id", "date"], how="left")
    comparison["change_reason"] = comparison.change_reason.fillna("No GPS change")
    comparison["gps_change_km"] = comparison.gps_filtered_km_after - comparison.gps_filtered_km_before
    comparison.to_csv(ROOT / "comparison_daily.csv", index=False, encoding="utf-8-sig")
    change_columns = ["device_id", "source_file", "source_sheet", "source_row", "timestamp", "latitude", "longitude", "gps_filtered_segment_km_before", "gps_filtered_segment_km_after", "gps_change_km", "gps_segment_start_index", "gps_segment_end_index", "gps_segment_class", "gps_segment_reason", "algorithm_status_before", "algorithm_status_after"]
    changes[change_columns].to_csv(ROOT / "changed_segments.csv", index=False, encoding="utf-8-sig")
    per_file = result.file_daily.groupby("source_file", dropna=False).sum(numeric_only=True).reset_index()
    per_file.to_csv(ROOT / "per_file.csv", index=False, encoding="utf-8-sig")
    # Explicitly locate the trusted spans contributing to GPS/counter differences.
    trusted = result.segments[result.segments.gps_segment_class.eq("TRUSTED")].copy()
    trusted["gps_minus_counter_km"] = trusted.gps_filtered_segment_km - trusted.device_counter_span_km
    excess_columns = ["device_id", "start_timestamp", "end_timestamp", "start_source_row", "end_source_row", "start_latitude", "start_longitude", "end_latitude", "end_longitude", "gps_filtered_segment_km", "device_counter_span_km", "gps_minus_counter_km"]
    excess = trusted.nlargest(500, "gps_minus_counter_km")[excess_columns]
    excess.to_csv(ROOT / "gps_excess_segments.csv", index=False, encoding="utf-8-sig")
    decomposition = []
    for device, spans in result.segments.groupby("device_id"):
        kept = spans[spans.gps_segment_class.eq("TRUSTED")]
        stopped = kept.start_device_speed_kmh.le(result.settings.stop_speed_kmh) & kept.end_device_speed_kmh.le(result.settings.stop_speed_kmh) & kept.device_counter_span_km.eq(0)
        stopped_gps = kept.loc[stopped, "gps_filtered_segment_km"].sum()
        other_excess = (kept.gps_filtered_segment_km - kept.device_counter_span_km).sum() - stopped_gps
        counter_outside = spans.loc[~spans.gps_segment_class.eq("TRUSTED"), "device_counter_span_km"].sum()
        observed = result.reconciliation[result.reconciliation.device_id.eq(device)].iloc[0]
        actual_difference = observed.gps_filtered_km - observed.device_period_original_km
        assert np.isclose(actual_difference, stopped_gps + other_excess - counter_outside, atol=1e-7)
        decomposition.append({"device_id": device, "gps_minus_period_counter_km": actual_difference, "trusted_gps_at_reported_stop_no_counter_increase_km": stopped_gps, "other_trusted_gps_minus_counter_km": other_excess, "counter_km_outside_trusted_gps_spans": counter_outside})
    decomposition = pd.DataFrame(decomposition)
    decomposition.to_csv(ROOT / "gps_excess_decomposition.csv", index=False, encoding="utf-8-sig")
    report = export_reconciliation_report(result, ROOT / "GPS_Journey_Analyzer_V1.2_Audit.xlsx", comparison, per_file,
        {"Phân rã chênh lệch GPS": decomposition, "Đoạn GPS vượt công tơ": excess, "Đoạn GPS thay đổi": changes[change_columns]})
    print("REPORT", report, flush=True)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name] for p in files)
    print("SOURCE SHA256: all unchanged", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "after", "report"])
    args = parser.parse_args()
    baseline() if args.phase == "baseline" else after(reuse_details=args.phase == "report")
