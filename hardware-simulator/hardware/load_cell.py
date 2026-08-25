"""Simulated load cell: deterministic profile with configurable gaussian
noise. Mirrors reading a physical HX711-like channel at 10 Hz."""
from __future__ import annotations

import random
from collections.abc import Callable


class LoadCell:
    def __init__(
        self,
        noise_grams: float = 0.2,
        seed: int | None = None,
        profile_offset: float = 0.0,
    ) -> None:
        self.noise_grams = noise_grams
        self._rng = random.Random(seed)
        self._current_value: float = profile_offset
        self.read_overrides: dict[float, float] = {}  # elapsed_seconds -> reading

    def set_readings(self, elapsed_seconds: float) -> None:
        """Drive the sensor to the value defined for this elapsed time in the
        simulated deposit plan (the 'real' weight including settle ramp)."""
        if elapsed_seconds in self.read_overrides:
            self._current_value = self.read_overrides[elapsed_seconds]

    def set_value(self, grams: float) -> None:
        """Directly sets the physical reading (backed by the ADC trace)."""
        self._current_value = grams

    def read_weight(self) -> float:
        noise = self._rng.uniform(-self.noise_grams, self.noise_grams)
        return round(self._current_value + noise, 2)

    def apply(self, seconds: float) -> float:
        self.set_readings(seconds)
        return self.read_weight()

    def __repr__(self) -> str:  # pragma: no cover
        return f"LoadCell(value={self._current_value:g}±{self.noise_grams})"


def settle_profile(timeline: list[tuple[float, float]]) -> Callable[[float], float]:
    """Builds a piecewise weight ramp from (elapsed_seconds, weight_grams)
    breakpoints, then clamps to the max after settle — the classic ADC trace:

        0.0 s -> 0g, 0.8 s -> 4g, 1.4 s -> 12g, 2.0 s -> 18.4g (stable)"""
    points = sorted(timeline, key=lambda p: p[0])
    max_weight = max(p[1] for p in points)

    def ramped(elapsed: float) -> float:
        if elapsed <= points[0][0]:
            return points[0][1]
        for (t0, w0), (t1, w1) in zip(points, points[1:]):
            if t0 <= elapsed <= t1:
                span = max(t1 - t0, 1e-6)
                return w0 + (w1 - w0) * ((elapsed - t0) / span)
        return max_weight

    return ramped