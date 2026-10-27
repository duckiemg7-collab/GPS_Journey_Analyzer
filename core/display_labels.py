from __future__ import annotations


WARNING_STATUS_LABELS = {
    "VALID": "Hợp lệ",
    "CONFIRMED_OUTLIER": "Nhiễu GPS đã xác nhận",
    "SUSPECTED_NOISE": "Nghi nhiễu GPS",
    "GPS_GAP": "Mất tín hiệu GPS",
    "GPS_DRIFT": "Trôi tọa độ GPS",
    "INVALID_COORDINATE": "Tọa độ không hợp lệ",
    "DUPLICATE": "Bản ghi trùng",
    "NEED_REVIEW": "Cần kiểm tra",
    "DEVICE_NEED_REVIEW": "Km thiết bị cần kiểm tra",
    "CONFIRMED": "Đã xác nhận",
}


EVENT_TYPE_LABELS = {
    "GPS Teleport": "GPS nhảy vị trí",
    "GPS Drift": "GPS trôi tọa độ",
    "Stationary GPS Cloud": "Cụm GPS trôi khi xe đứng yên",
    "GPS Signal Loss": "Mất tín hiệu GPS",
    "GPS Jump and Return": "GPS nhảy xa rồi quay lại",
    "GPS Cluster Outlier": "Cụm nhiễu GPS",
    "Device Distance Anomaly": "Km thiết bị bất thường",
    "Timestamp Error": "Lỗi thời gian",
}


def warning_status_label(value: object) -> str:
    text = str(value or "")
    return WARNING_STATUS_LABELS.get(text, text)


def event_type_label(value: object) -> str:
    text = str(value or "")
    return EVENT_TYPE_LABELS.get(text, text)
