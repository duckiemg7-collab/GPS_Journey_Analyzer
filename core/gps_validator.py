from __future__ import annotations

import pandas as pd
from core.excel_reader import _parse_timestamps, _plain


def validate_and_sort(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.copy()
    # Mixed Excel strings must be parsed individually; global inference can
    # swap day/month on files that store time before date.
    frame["timestamp"] = _parse_timestamps(frame["timestamp"])
    frame["device_km"] = pd.to_numeric(frame["device_km"], errors="coerce")
    for column in ("latitude", "longitude", "device_speed_kmh"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values(
        ["device_id", "timestamp", "input_order"], na_position="last", kind="stable"
    ).reset_index(drop=True)
    frame["algorithm_status"] = "VALID"
    frame["warning_reason"] = ""
    frame["exclude_from_gps"] = False

    invalid_coord = (
        frame["latitude"].isna()
        | frame["longitude"].isna()
        | ~frame["latitude"].between(-90, 90)
        | ~frame["longitude"].between(-180, 180)
    )
    zero = frame.latitude.eq(0) & frame.longitude.eq(0)
    zero_run = (zero.ne(zero.shift()) | frame.device_id.ne(frame.device_id.shift())).cumsum()
    loss = frame.device_status.map(_plain).str.contains(r"\b(?:mat gps|mat tin hieu|gps lost|no gps)\b", na=False)
    # (0,0) itself is a valid place. Only treat a contiguous zero run as a
    # missing fix when that same run contains explicit signal-loss evidence.
    frame["no_fix_coordinate"] = zero & loss.groupby(zero_run).transform("any")
    invalid_coord |= frame.no_fix_coordinate
    frame.loc[invalid_coord, ["algorithm_status", "warning_reason", "exclude_from_gps"]] = [
        "INVALID_COORDINATE",
        "Tọa độ thiếu hoặc nằm ngoài miền hợp lệ",
        True,
    ]
    invalid_time = frame["timestamp"].isna()
    frame.loc[invalid_time, ["algorithm_status", "warning_reason", "exclude_from_gps"]] = [
        "NEED_REVIEW",
        "Timestamp không hợp lệ",
        True,
    ]

    key = ["device_id", "timestamp", "latitude", "longitude", "device_km"]
    duplicates = frame.duplicated(key, keep="first")
    frame.loc[duplicates, ["algorithm_status", "warning_reason", "exclude_from_gps"]] = [
        "DUPLICATE",
        "Bản ghi trùng hoặc chồng lấn giữa các file",
        True,
    ]
    duplicated_time = frame.duplicated(["device_id", "timestamp"], keep="first") & ~duplicates
    frame.loc[
        duplicated_time, ["algorithm_status", "warning_reason", "exclude_from_gps"]
    ] = ["NEED_REVIEW", "Timestamp trùng với bản ghi khác", True]
    frame["is_duplicate"] = duplicates
    frame["invalid_timestamp"] = invalid_time
    frame["timestamp_conflict"] = duplicated_time & ~invalid_time
    frame["invalid_coordinate"] = invalid_coord
    return frame

