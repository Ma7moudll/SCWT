"""Simulated carriage: moves between the four internal compartment positions
with realistic per-step timing (no teleporting) and an optional simulated
jam."""
from __future__ import annotations

from collections.abc import Iterator


class JamError(RuntimeError):
    """Raised when the carriage physically jams mid-move."""


class Carriage:
    def __init__(self, initial_position: int = 1, movement_time_per_step: float = 0.3) -> None:
        self.current_position = initial_position
        self.movement_time_per_step = movement_time_per_step
        self.jam_at_step: int | None = None  # 1-based step at which to jam

    def move_to(self, target: int) -> Iterator[int]:
        """Yields each intermediate position as the carriage traverses it.
        Movement time scales with distance: |Δpos| * per_step seconds.
        `jam_at_step` raises [JamError] on the given step instead of settling.

        Iterator is used so the Machine can publish progress telemetry per
        step exactly like an ESP32 would."""
        from time import sleep

        current = self.current_position
        if target == current:
            return
        step = 0
        direction = 1 if target > current else -1
        while current != target:
            step += 1
            if self.jam_at_step is not None and step == self.jam_at_step:
                raise JamError(f"carriage jammed on step {step} towards {target}")
            sleep(self.movement_time_per_step)
            current += direction
            self.current_position = current
            yield current

    def is_at_position(self, position: int) -> bool:
        return self.current_position == position

    def __repr__(self) -> str:  # pragma: no cover
        return f"Carriage(pos={self.current_position})"