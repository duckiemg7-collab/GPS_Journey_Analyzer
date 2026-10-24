from __future__ import annotations

import pandas as pd


def validate_and_sort(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.copy()
    # Mixed Excel strings must be parsed individually; global inference can
    # swap day/month on files that store time before date.
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], format="mixed", dayfirst=True, errors="coerce"
    )
    frame["device_km"] = pd.to_numeric(frame["device_km"], errors="coerce")
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
    return frame

