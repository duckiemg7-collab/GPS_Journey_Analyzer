from __future__ import annotations

import pandas as pd


def make_frame(rows, device="TEST01", source="synthetic.xlsx"):
    records = []
    for i, row in enumerate(rows):
        timestamp, lat, lon, speed, km, *rest = row
        records.append(
            {
                "device_id": device,
                "source_file": source,
                "source_sheet": device,
                "source_row": i + 4,
                "timestamp": pd.Timestamp(timestamp),
                "latitude": lat,
                "longitude": lon,
                "device_speed_kmh": speed,
                "device_km": km,
                "device_status": rest[0] if rest else "Chạy bình thường",
                "input_order": i,
            }
        )
    return pd.DataFrame(records)

