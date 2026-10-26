from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True, slots=True)
class FilterSettings:
    """Các ngưỡng có thể điều chỉnh từ giao diện."""

    max_plausible_speed_kmh: float = 120.0
    stop_speed_kmh: float = 3.0
    stop_radius_meters: float = 30.0
    max_gps_gap_seconds: int = 120
    mode: str = "Conservative"

    @property
    def mode_factor(self) -> float:
        return {"Conservative": 1.0, "Balanced": 0.85, "Aggressive": 0.7}.get(
            self.mode, 1.0
        )

    def effective(self) -> "FilterSettings":
        """Áp dụng preset nhưng không thay đổi giá trị người dùng đã nhập."""
        factor = self.mode_factor
        return replace(
            self,
            max_plausible_speed_kmh=self.max_plausible_speed_kmh * factor,
            stop_radius_meters=self.stop_radius_meters / factor,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


ALGORITHM_VERSION = "1.2.0"
EARTH_RADIUS_KM = 6371.0088

