from __future__ import annotations

import pandas as pd
import pytest
import json
from pathlib import Path

from config.settings import FilterSettings
from core.daily_aggregator import aggregate_daily
from core.gps_filter import detect_and_filter, _status_flags
from core.gps_validator import validate_and_sort
from core.haversine import point_distance_km
from tests.conftest import make_frame
from core.reconciliation import segment_view, assign_warning_events, period_reconciliation


def analyze(rows):
    return detect_and_filter(validate_and_sort(make_frame(rows)), FilterSettings())


def test_duplicate_does_not_break_following_valid_route():
    rows = [(f"2026-10-01 08:0{i}:00", 10 + i * .001, 106, 10, i * .1) for i in range(3)]
    expected = analyze(rows)["gps_filtered_segment_km"].sum()
    with_duplicate = analyze([rows[0], rows[1], rows[1], rows[2]])
    assert with_duplicate["gps_filtered_segment_km"].sum() == pytest.approx(expected)
    assert with_duplicate.loc[with_duplicate.algorithm_status == "DUPLICATE", "gps_unverified_segment_km"].sum() == 0


def test_gap_endpoint_can_start_a_new_continuous_route():
    data = analyze([
        ("2026-10-01 08:00:00", 10, 106, 10, 0),
        ("2026-10-01 08:10:00", 10.001, 106, 10, .1),
        ("2026-10-01 08:11:00", 10.002, 106, 10, .2),
    ])
    assert data.iloc[1].gps_unverified_segment_km == pytest.approx(point_distance_km(10, 106, 10.001, 106))
    assert data.iloc[2].gps_filtered_segment_km == pytest.approx(point_distance_km(10.001, 106, 10.002, 106))


def test_reconstruct_after_spike_without_readding_spike():
    data = analyze([
        ("2026-10-01 08:00:00", 10, 106, 30, 0),
        ("2026-10-01 08:00:10", 10.2, 106, 30, 0),
        ("2026-10-01 08:00:20", 10.001, 106, 30, .1),
        ("2026-10-01 08:00:30", 10.002, 106, 30, .2),
    ])
    assert data.gps_filtered_segment_km.sum() == pytest.approx(point_distance_km(10, 106, 10.002, 106))
    assert data.iloc[2].gps_segment_start_index == 0
    assert data.iloc[2].gps_segment_class == "TRUSTED"


def test_stopped_status_does_not_match_running_word():
    assert not _status_flags("Hoạt động")[0]
    assert not _status_flags("Đang chạy")[0]
    assert _status_flags("Dừng đỗ")[0]


def test_iso_timestamp_is_not_reinterpreted_day_first():
    raw = make_frame([("2026-10-06 11:09:10", 10, 106, 0, 0)])
    raw["timestamp"] = "2026-10-06T11:09:10.000"
    assert validate_and_sort(raw).iloc[0].timestamp == pd.Timestamp("2026-10-06 11:09:10")


def test_returning_cluster_with_reset_never_confirms_counter_subtraction():
    data = analyze([
        ("2026-10-01 08:00:00", 10, 106, 0, 100, "Xe dừng"),
        ("2026-10-01 08:01:00", 10.2, 106, 0, 0, "Xe dừng"),
        ("2026-10-01 08:02:00", 10.2, 106, 0, 0, "Xe dừng"),
        ("2026-10-01 08:03:00", 10, 106, 0, 120, "Xe dừng"),
    ])
    assert data.confirmed_false_km.sum() == 0


def test_midnight_daily_plus_unallocated_reconciles_period_counter():
    data = analyze([
        ("2026-10-01 23:59:50", 10, 106, 30, 10),
        ("2026-10-02 00:00:10", 10.001, 106, 30, 10.1),
        ("2026-10-02 00:01:10", 10.002, 106, 30, 10.2),
    ])
    daily = aggregate_daily(data)
    assert daily.unallocated_device_km.sum() == pytest.approx(.1)
    assert daily.device_original_km.sum() + daily.unallocated_device_km.sum() == pytest.approx(.2)


def test_invalid_timestamp_is_counted_but_never_allocated_to_a_day():
    raw = make_frame([("2026-10-01 08:00:00", 10, 106, 0, 1), ("2026-10-01 08:01:00", 10, 106, 0, 2)])
    raw.loc[1, "timestamp"] = pd.NaT
    from core.pipeline import analyze_records
    result = analyze_records(raw, [])
    assert result.daily.record_count.sum() == 2
    assert result.daily[result.daily.date.isna()].record_count.sum() == 1
    assert result.totals["device_original_km"] is None


def test_counter_evidence_has_unique_edge_ids_and_no_deductions():
    from core.pipeline import analyze_records
    raw = make_frame([
        ("2026-10-01 08:00:00", 10, 106, 0, 0),
        ("2026-10-01 08:00:10", 10.1, 106, 0, 10),
        ("2026-10-01 08:00:20", 10, 106, 0, 20),
    ])
    result = analyze_records(raw, [])
    evidence = result.counter_evidence
    assert evidence.counter_edge_id.is_unique
    assert evidence.deducted_km.sum() == 0
    assert set(evidence.confirmation_status) == {"NEED_REVIEW"}
    assert evidence.start_timestamp.notna().all()
    assert evidence.end_timestamp.notna().all()
    assert not result.daily.warnings.str.contains(r"\bVALID:").any()


def test_zero_coordinate_loss_cluster_is_not_a_ten_thousand_km_reference():
    data = analyze([
        ("2026-10-01 23:59:50", 10, -106, 30, 10, "Đang chạy"),
        ("2026-10-02 00:00:10", 0, 0, 0, 10, "Xe mất GPS"),
        ("2026-10-02 00:00:11", 0, 0, 0, 10, "Xe dừng"),
        ("2026-10-02 00:01:00", 10.001, -106, 30, 10.1, "Đang chạy"),
    ])
    assert data.iloc[1].invalid_coordinate
    assert data.iloc[2].invalid_coordinate
    assert data.gps_unverified_segment_km.sum() == pytest.approx(point_distance_km(10, -106, 10.001, -106))
    assert data.gps_filtered_segment_km.sum() == 0


def test_zero_coordinate_without_loss_evidence_is_geographically_valid():
    data = analyze([("2026-10-01 08:00:00", 0, 0, 10, 0), ("2026-10-01 08:01:00", .001, 0, 10, .1)])
    assert not data.iloc[0].invalid_coordinate
    assert data.gps_filtered_segment_km.sum() == pytest.approx(point_distance_km(0, 0, .001, 0))


def test_invalid_coordinate_status_survives_drift_detection():
    data = analyze([("2026-10-01 08:00:00", 10, 106, 0, 0), ("2026-10-01 08:01:00", 91, 106, 0, 0)])
    assert data.iloc[1].algorithm_status == "INVALID_COORDINATE"
    assert data.gps_filtered_segment_km.sum() == 0


def test_confirmed_cluster_endpoints_never_inflate_unverified_reference():
    data = analyze([
        ("2026-10-01 08:00:00", 10, 106, 0, 0, "Xe dừng"),
        ("2026-10-01 08:01:00", 10.2, 106, 0, 0, "Xe dừng"),
        ("2026-10-01 08:10:00", 10.2, 106, 0, 0, "Xe dừng"),
        ("2026-10-01 08:11:00", 10, 106, 0, 0, "Xe dừng"),
    ])
    assert data.gps_unverified_segment_km.sum() == pytest.approx(0)
    assert data.gps_confirmed_outlier_segment_km.sum() == pytest.approx(2 * point_distance_km(10, 106, 10.2, 106))


def test_raw_counts_and_warnings_include_duplicates_in_daily():
    row = ("2026-10-01 08:00:00", 10, 106, 0, 1)
    data = analyze([row, row])
    daily = aggregate_daily(data)
    assert daily.record_count.sum() == len(data)
    assert daily.warning_count.sum() == (data.algorithm_status != "VALID").sum()


@pytest.mark.parametrize("distance,seconds", [(.3, 1), (.7, 5), (2, 30), (18, 60)])
def test_impossible_edge_exact_haversine_is_not_trusted(distance, seconds):
    end = pd.Timestamp("2026-10-01 08:00:00") + pd.Timedelta(seconds=seconds)
    data = analyze([("2026-10-01 08:00:00", 10, 106, 30, 0), (end, 10 + distance / 111, 106, 30, distance)])
    expected = point_distance_km(10, 106, 10 + distance / 111, 106)
    assert data.iloc[1].gps_speed_kmh == pytest.approx(expected * 3600 / seconds)
    assert data.gps_filtered_segment_km.sum() == 0
    assert data.gps_unverified_segment_km.sum() == pytest.approx(expected)


FIXTURE = json.loads((Path(__file__).parent / "fixtures/50CD00062_events.json").read_text(encoding="utf-8"))


def test_real_zero_fix_cluster_has_no_global_teleport_reference():
    fixture = json.loads((Path(__file__).parent / "fixtures/51D83217_no_fix.json").read_text(encoding="utf-8"))
    raw = pd.DataFrame(fixture["records"])
    data = detect_and_filter(validate_and_sort(raw), FilterSettings())
    zeros = data.latitude.eq(0) & data.longitude.eq(0)
    assert zeros.any()
    assert data.loc[zeros, "no_fix_coordinate"].all()
    assert data.raw_distance_km.max() > 10000  # raw diagnostic retains the source geometry
    first_zero, last_zero = data.loc[zeros, "timestamp"].min(), data.loc[zeros, "timestamp"].max()
    start = data[data.timestamp.lt(first_zero) & data.counter_eligible].iloc[-1]
    end = data[data.timestamp.gt(last_zero) & data.counter_eligible].iloc[0]
    assert end.gps_unverified_segment_km == pytest.approx(point_distance_km(start.latitude, start.longitude, end.latitude, end.longitude))
    assert data.loc[zeros, "gps_filtered_segment_km"].sum() == 0


@pytest.mark.parametrize("event", FIXTURE["events"], ids=lambda event: event["target"])
def test_real_50cd00062_signal_reacquisition(event):
    raw = pd.DataFrame(event["records"])
    data = detect_and_filter(validate_and_sort(raw), FilterSettings())
    target = data.loc[data.timestamp.eq(pd.Timestamp(event["target"]))].iloc[0]
    start = data.loc[int(target.pair_start_index)]
    expected_distance = point_distance_km(start.latitude, start.longitude, target.latitude, target.longitude)
    expected_seconds = (target.timestamp - start.timestamp).total_seconds()
    assert target.gps_speed_kmh == pytest.approx(expected_distance * 3600 / expected_seconds)
    assert target.gps_speed_kmh > FilterSettings().max_plausible_speed_kmh
    assert target.algorithm_status == "GPS_GAP"
    assert target.gps_filtered_segment_km == 0
    assert target.gps_unverified_segment_km == pytest.approx(expected_distance)
    assert target.device_km_delta == pytest.approx(target.device_km - start.device_km)
    assert target.confirmed_false_km == 0
    next_row = data.loc[data.timestamp.gt(target.timestamp)].iloc[0]
    assert next_row.gps_filtered_segment_km == pytest.approx(point_distance_km(target.latitude, target.longitude, next_row.latitude, next_row.longitude))
    assert raw.source_row.notna().all()


def test_segment_intervals_partition_canonical_edges_and_raw_distance():
    data = analyze([
        ("2026-10-01 08:00:00", 10, 106, 30, 0),
        ("2026-10-01 08:00:10", 10.2, 106, 30, 0),
        ("2026-10-01 08:00:20", 10.001, 106, 30, .1),
        ("2026-10-01 08:00:30", 10.002, 106, 30, .2),
        ("2026-10-01 08:10:00", 10.1, 106, 30, .3),
    ])
    segments = segment_view(data)
    covered = []
    for _, segment in segments.iterrows():
        a, b = int(segment.gps_segment_start_index), int(segment.gps_segment_end_index)
        covered.extend(range(a + 1, b + 1))
        assert segment.gps_segment_reference_km == pytest.approx(point_distance_km(segment.start_latitude, segment.start_longitude, segment.end_latitude, segment.end_longitude))
    assert covered == list(range(1, len(data)))
    assert segments.gps_segment_raw_km.sum() == pytest.approx(data.raw_distance_km.sum())
    assert not ((segments.gps_filtered_segment_km > 0) & (segments.gps_unverified_segment_km > 0)).any()


def test_overlapping_file_views_use_same_counter_edges_as_period():
    a = make_frame([("2026-10-01 08:00:00", 10, 106, 10, 0), ("2026-10-01 08:01:00", 10.001, 106, 10, .1)], source="a.xlsx")
    b = make_frame([("2026-10-01 08:01:00", 10.001, 106, 10, .1), ("2026-10-01 08:02:00", 10.002, 106, 10, .2)], source="b.xlsx")
    b.input_order += len(a)
    data = assign_warning_events(detect_and_filter(validate_and_sort(pd.concat([a, b])), FilterSettings()))
    daily = aggregate_daily(data)
    files = aggregate_daily(data, by_source_file=True)
    assert daily.device_original_km.sum() == pytest.approx(.2)
    assert files.device_original_km.sum() == pytest.approx(.2)
    assert files.record_count.sum() == len(data)
    assert period_reconciliation(data, daily).counter_reconciliation_difference_km.sum() == pytest.approx(0)
