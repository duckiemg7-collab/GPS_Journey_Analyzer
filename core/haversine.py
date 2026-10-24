from __future__ import annotations

import numpy as np

from config.settings import EARTH_RADIUS_KM


def haversine_km(lat1, lon1, lat2, lon2):
    """Khoảng cách Haversine; hỗ trợ cả scalar và numpy array."""
    lat1r, lon1r, lat2r, lon2r = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(
        dlon / 2.0
    ) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def point_distance_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    return float(haversine_km(a_lat, a_lon, b_lat, b_lon))

