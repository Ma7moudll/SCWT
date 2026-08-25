"""Simulated IR/beam, position and door sensors."""
from __future__ import annotations


class BeamSensor:
    """IR beam across the station opening. `broken=True` while an object
    interrupts the beam."""

    def __init__(self, broken: bool = False) -> None:
        self.broken = broken

    def set(self, broken: bool) -> None:
        self.broken = broken

    def read(self) -> bool:
        return self.broken


class PositionSensor:
    """Reports which compartment the carriage is physically aligned with."""

    def __init__(self, positions: tuple[int, ...] = (1, 2, 3, 4), current: int = 1) -> None:
        self.positions = positions
        self.current = current

    def set(self, position: int) -> None:
        if position not in self.positions:
            raise ValueError(f"unknown position {position}")
        self.current = position

    def read(self) -> int:
        return self.current


class DoorSensor:
    def __init__(self, state: str = "CLOSED") -> None:
        self.state = state

    def set(self, state: str) -> None:
        self.state = state

    def read(self) -> str:
        return self.state