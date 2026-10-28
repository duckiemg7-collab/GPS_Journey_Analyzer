from __future__ import annotations

from dataclasses import asdict, dataclass, replace


SPEED_NUMERIC_TOLERANCE_FACTOR = 1.02


@dataclass(frozen=True, slots=True)
class FilterSettings:
    """Các ngưỡng có thể điều chỉnh từ giao diện."""

    max_plausible_speed_kmh: float = 120.0
    stop_speed_kmh: float = 3.0
    stop_radius_meters: float = 30.0
    max_gps_gap_seconds: int = 120
    mode: str = "Conservative"

    def __post_init__(self) -> None:
        if not 20 <= self.max_plausible_speed_kmh <= 500:
            raise ValueError("Tốc độ GPS tối đa phải nằm trong khoảng 20–500 km/h")
        if not 0 <= self.stop_speed_kmh <= 30:
            raise ValueError("Ngưỡng xe dừng phải nằm trong khoảng 0–30 km/h")
        if not 1 <= self.stop_radius_meters <= 1000:
            raise ValueError("Bán kính dừng phải nằm trong khoảng 1–1000 m")
        if not 1 <= self.max_gps_gap_seconds <= 86400:
            raise ValueError("Khoảng mất GPS phải nằm trong khoảng 1–86400 giây")
        if self.mode not in {"Conservative", "Balanced", "Aggressive"}:
            raise ValueError(f"Chế độ lọc không hợp lệ: {self.mode}")

    @property
    def mode_factor(self) -> float:
        return {"Conservative": 1.0, "Balanced": 0.85, "Aggressive": 0.7}.get(
            self.mode, 1.0
        )

    def effective(self) -> "FilterSettings":
        """Return the actual thresholds used by the GPS filter.

        Modes tune detection sensitivity only.  They never relax a physically
        impossible edge or alter device-counter distance.
        """
        factor = self.mode_factor
        return replace(
            self,
            # The 2% numerical margin avoids classifying a boundary edge from
            # Haversine/coordinate rounding as impossible.  It is part of the
            # displayed effective threshold rather than a hidden filter rule.
            max_plausible_speed_kmh=min(
                500.0,
                self.max_plausible_speed_kmh * factor * SPEED_NUMERIC_TOLERANCE_FACTOR,
            ),
            # A smaller radius detects stationary drift sooner.  The previous
            # division made Aggressive less sensitive on this branch.
            stop_radius_meters=max(1.0, self.stop_radius_meters * factor),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def describe(self, *, effective: bool = False) -> str:
        value = self.effective() if effective else self
        return (
            f"mode={value.mode}, max_speed={value.max_plausible_speed_kmh:g} km/h, "
            f"stop_speed={value.stop_speed_kmh:g} km/h, "
            f"stop_radius={value.stop_radius_meters:g} m, "
            f"max_gap={value.max_gps_gap_seconds} s"
        )


ALGORITHM_VERSION = "1.2.1"
EARTH_RADIUS_KM = 6371.0088

