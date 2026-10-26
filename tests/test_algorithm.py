from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from config.settings import FilterSettings
from core.daily_aggregator import aggregate_daily
from core.excel_reader import _parse_timestamps
from core.gps_filter import detect_and_filter
from core.gps_validator import validate_and_sort
from tests.conftest import make_frame


def edge_rows(distance_km: float, seconds: int, device_speed: float, status: str = "Chạy bình thường"):
    latitude = 10.0 + distance_km / 111.0
    timestamp = datetime(2026, 10, 1, 8, 0, 0) + timedelta(seconds=seconds)
    second_km = 0.0 if device_speed == 0 else distance_km
    return [
        ("2026-10-01 08:00:00", 10.0, 106.0, device_speed, 0.0, status),
        (timestamp.strftime("%Y-%m-%d %H:%M:%S"), latitude, 106.0, device_speed, second_km, status),
    ]


def run(rows):
    return detect_and_filter(validate_and_sort(make_frame(rows)), FilterSettings())


def test_stopped_vehicle_gps_drift():
    data = run(
        [
            ("2026-10-01 10:00:00", 10.0, 106.0, 0, 10.0),
            ("2026-10-01 10:00:10", 10.001, 106.0, 0, 10.0),
            ("2026-10-01 10:00:20", 10.0, 106.0, 0, 10.0),
        ]
    )
    assert (data["algorithm_status"] == "GPS_DRIFT").sum() == 2
    assert data["gps_filtered_segment_km"].sum() == 0


@pytest.mark.parametrize("distance_km", [0.3, 0.7, 2.0, 18.0])
@pytest.mark.parametrize("seconds", [1, 5, 30, 60, 300])
def test_stopped_distance_is_unverified_at_any_jump_size(distance_km, seconds):
    data = run(edge_rows(distance_km, seconds, 0.0, "Xe dừng"))
    assert data.iloc[1]["exclude_from_gps"]
    assert data.iloc[1]["gps_filtered_segment_km"] == 0
    assert data.iloc[1]["gps_unverified_segment_km"] > 0


@pytest.mark.parametrize(
    "distance_km,seconds,expected_excluded",
    [
        (0.3, 1, True),
        (0.3, 5, True),
        (0.3, 30, False),
        (0.7, 30, False),
        (2.0, 60, False),
        (18.0, 300, True),
    ],
)
def test_moving_jump_uses_time_and_speed_not_distance_cutoff(distance_km, seconds, expected_excluded):
    speed = distance_km / seconds * 3600
    data = run(edge_rows(distance_km, seconds, speed))
    assert bool(data.iloc[1]["exclude_from_gps"]) is expected_excluded


def test_jump_18_km_and_return_confirms_false_device_km():
    data = run(
        [
            ("2026-10-03 09:30:00", 10.7062, -106.6057, 0, 100.0, "Xe dừng"),
            ("2026-10-03 09:31:00", 10.6086, -106.7433, 0, 100.0, "Xe dừng"),
            ("2026-10-03 09:40:00", 10.6086, -106.7433, 0, 100.0, "Xe dừng"),
            ("2026-10-03 09:41:00", 10.7062, -106.6057, 5, 118.5, "Xe chạy lại"),
        ]
    )
    assert (data["algorithm_status"] == "CONFIRMED_OUTLIER").sum() == 2
    assert data["confirmed_false_km"].sum() == pytest.approx(18.5)
    assert data["gps_filtered_segment_km"].sum() == pytest.approx(0)


def test_returning_cluster_does_not_write_off_counter_progress_inside_cluster():
    data = run(
        [
            ("2026-10-03 09:30:00", 10.7062, -106.6057, 0, 100.0, "Xe dừng"),
            ("2026-10-03 09:31:00", 10.6086, -106.7433, 0, 101.0, "Xe dừng"),
            ("2026-10-03 09:40:00", 10.6086, -106.7433, 0, 102.0, "Xe dừng"),
            ("2026-10-03 09:41:00", 10.7062, -106.6057, 5, 118.5, "Xe chạy lại"),
        ]
    )
    assert data["confirmed_false_km"].sum() == pytest.approx(0.0)
    assert data["gps_unverified_segment_km"].sum() > 0


def test_multi_point_fake_cluster():
    rows = [("2026-10-04 13:40:00", 10.7060, -106.6056, 0, 20.0, "Xe dừng")]
    rows += [
        (f"2026-10-04 13:{41+i:02d}:00", 10.79 + i * 0.00001, -106.68, 0, 20.0, "Xe dừng")
        for i in range(5)
    ]
    rows += [("2026-10-04 13:47:00", 10.7060, -106.6056, 3, 24.4, "Xe chạy lại")]
    data = run(rows)
    assert (data["algorithm_status"] == "CONFIRMED_OUTLIER").sum() == 5
    assert data["confirmed_false_km"].sum() == pytest.approx(4.4)


def test_normal_movement_is_kept():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.7000, -106.6000, 30, 0.0),
            ("2026-10-01 08:01:00", 10.7040, -106.6000, 30, 0.4),
            ("2026-10-01 08:02:00", 10.7080, -106.6000, 30, 0.8),
        ]
    )
    assert set(data["algorithm_status"]) == {"VALID"}
    assert data["gps_filtered_segment_km"].sum() > 0.8


def test_long_gps_gap_is_not_connected():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.70, -106.60, 20, 0.0),
            ("2026-10-01 08:10:00", 10.71, -106.60, 20, 1.1),
        ]
    )
    assert data.iloc[1]["algorithm_status"] == "GPS_GAP"
    assert data.iloc[1]["gps_filtered_segment_km"] == 0


def test_duplicate_record_is_preserved_and_flagged():
    rows = [
        ("2026-10-01 08:00:00", 10.7, -106.6, 0, 0.0),
        ("2026-10-01 08:00:00", 10.7, -106.6, 0, 0.0),
    ]
    data = detect_and_filter(validate_and_sort(make_frame(rows)), FilterSettings())
    assert len(data) == 2
    assert data.iloc[1]["algorithm_status"] == "DUPLICATE"


def test_duplicate_timestamp_with_different_position_needs_review():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.7, -106.6, 0, 0.0),
            ("2026-10-01 08:00:00", 10.8, -106.7, 0, 0.0),
        ]
    )
    assert data.iloc[1]["algorithm_status"] == "NEED_REVIEW"


def test_overlapping_files_do_not_double_count():
    first = make_frame(
        [
            ("2026-10-01 08:00:00", 10.7, -106.6, 20, 0.0),
            ("2026-10-01 08:01:00", 10.704, -106.6, 20, 0.4),
        ],
        source="a.xlsx",
    )
    second = first.copy()
    second["source_file"] = "b.xlsx"
    second["input_order"] += 2
    data = detect_and_filter(validate_and_sort(pd.concat([first, second])), FilterSettings())
    combined = aggregate_daily(data)
    assert len(combined) == 1
    assert combined.iloc[0]["device_original_km"] == pytest.approx(0.4)
    daily = aggregate_daily(data, by_source_file=True)
    assert (data["algorithm_status"] == "DUPLICATE").sum() == 2
    assert daily.iloc[0]["device_original_km"] == pytest.approx(0.4)


def test_daily_summary_keeps_same_device_files_separate():
    first = make_frame(
        [
            ("2026-10-01 08:00:00", 10.7, -106.6, 20, 0.0),
            ("2026-10-01 08:01:00", 10.704, -106.6, 20, 0.4),
        ],
        source="bao_cao_1.xlsx",
    )
    second = make_frame(
        [
            ("2026-10-01 08:00:00", 10.8, -106.7, 20, 0.0),
            ("2026-10-01 08:01:00", 10.804, -106.7, 20, 0.6),
        ],
        source="bao_cao_2.xlsx",
    )
    data = detect_and_filter(validate_and_sort(pd.concat([first, second])), FilterSettings())
    daily = aggregate_daily(data, by_source_file=True)
    assert list(daily["source_file"]) == ["bao_cao_1.xlsx", "bao_cao_2.xlsx"]
    assert list(daily["device_original_km"]) == pytest.approx([0.4, 0.6])


def test_excel_timestamp_with_time_first_keeps_day_month_order():
    values = pd.Series(
        [
            "00:00:10 01-10-2026",
            "00:02:00 02-10-2026",
            "23:59:50 08-10-2026",
        ]
    )
    parsed = _parse_timestamps(values)
    assert parsed.dt.strftime("%Y-%m-%d").tolist() == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-08",
    ]


def test_midnight_segment_not_added_to_either_day():
    data = run(
        [
            ("2026-10-01 23:59:50", 10.7, -106.6, 30, 10.0),
            ("2026-10-02 00:00:10", 10.71, -106.6, 30, 11.0),
            ("2026-10-02 00:01:10", 10.714, -106.6, 30, 11.4),
        ]
    )
    daily = aggregate_daily(data)
    assert data.iloc[1]["gps_filtered_segment_km"] == 0
    assert daily.loc[daily["date"] == pd.Timestamp("2026-10-02").date(), "device_original_km"].iloc[0] == pytest.approx(0.4)
    assert daily.loc[daily["date"] == pd.Timestamp("2026-10-02").date(), "device_unallocated_km"].iloc[0] == pytest.approx(1.0)


def test_unverified_segment_keeps_actual_accepted_endpoint_pair():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.0000, -106.0, 30, 0.0),
            ("2026-10-01 08:01:00", 10.1000, -106.0, 30, 1.0),
            ("2026-10-01 08:02:00", 10.1010, -106.0, 30, 1.0),
        ]
    )
    row = data.iloc[1]
    assert row["gps_unverified_start_index"] == 0
    assert row["gps_unverified_end_index"] == 1
    assert row["gps_unverified_segment_km"] == pytest.approx(row["raw_distance_km"])
    assert data.iloc[2]["gps_unverified_segment_km"] == 0


def test_unknown_speed_is_not_treated_as_stopped():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.0, -106.0, None, 0.0, ""),
            ("2026-10-01 08:01:00", 10.01, -106.0, None, 1.0, ""),
        ]
    )
    assert data.iloc[1]["algorithm_status"] == "VALID"
    assert data.iloc[1]["gps_filtered_segment_km"] > 0


@pytest.mark.parametrize("status", ["Dừng đỗ", "STOP", "Đang đỗ xe"])
def test_excel_stop_status_mapping_marks_coordinate_drift(status):
    data = run(
        [
            ("2026-10-01 08:00:00", 10.0, -106.0, None, 0.0, status),
            ("2026-10-01 08:00:10", 10.01, -106.0, None, 0.0, status),
        ]
    )
    assert data.iloc[1]["algorithm_status"] == "GPS_DRIFT"


def test_signal_loss_status_creates_unverified_gap():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.0, -106.0, 30, 0.0, "Đang chạy"),
            ("2026-10-01 08:01:00", 10.01, -106.0, 30, 0.2, "Mất tín hiệu GPS"),
        ]
    )
    assert data.iloc[1]["algorithm_status"] == "GPS_GAP"
    assert data.iloc[1]["gps_unverified_segment_km"] > 0


def test_filtered_and_unverified_segments_are_disjoint():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.0, -106.0, 30, 0.0),
            ("2026-10-01 08:01:00", 10.1, -106.0, 30, 1.0),
            ("2026-10-01 08:02:00", 10.2, -106.0, 30, 2.0),
        ]
    )
    assert not ((data["gps_filtered_segment_km"] > 0) & (data["gps_unverified_segment_km"] > 0)).any()
    assert (data["confirmed_false_km"] >= 0).all()


def test_device_counter_reset_only_sums_positive_deltas():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.700, -106.6, 20, 100.0),
            ("2026-10-01 08:01:00", 10.704, -106.6, 20, 100.4),
            ("2026-10-01 08:02:00", 10.708, -106.6, 20, 0.0),
            ("2026-10-01 08:03:00", 10.712, -106.6, 20, 0.4),
        ]
    )
    assert aggregate_daily(data).iloc[0]["device_original_km"] == pytest.approx(0.8)


def test_insufficient_gps_returns_na_not_zero():
    data = run([("2026-10-01 08:00:00", None, None, 0, 0.0)])
    assert math.isnan(aggregate_daily(data).iloc[0]["gps_filtered_km"])


def test_device_and_gps_distances_are_independent():
    data = run(
        [
            ("2026-10-01 08:00:00", 10.700, -106.6, 30, 0.0),
            ("2026-10-01 08:01:00", 10.704, -106.6, 30, 5.0),
        ]
    )
    daily = aggregate_daily(data).iloc[0]
    assert daily["device_original_km"] == pytest.approx(5.0)
    assert daily["gps_filtered_km"] != pytest.approx(5.0)

