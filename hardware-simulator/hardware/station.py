from __future__ import annotations

import time
from typing import Callable

from .carriage import Carriage, JamError
from .load_cell import LoadCell
from .sensors import BeamSensor, PositionSensor
from .state_machine import MachineState, StateMachine

DEFAULT_POSITIONS = (1, 2, 3, 4)


class Station:
    """The simulated EcoLoop unit: one body, four internal compartment
    positions, an internal carriage, a load cell and an IR beam.

    This class IS the future ESP32 firmware driving real motors and reading
    real sensors — everything here speaks the documented MQTT contract.
    """

    def __init__(
        self,
        carriage: Carriage,
        load_cell: LoadCell,
        beam: BeamSensor,
        position_sensor: PositionSensor,
    ) -> None:
        self.carriage = carriage
        self.load_cell = load_cell
        self.beam = beam
        self.position_sensor = position_sensor
        self.machine = StateMachine()

    @property
    def state(self) -> MachineState:
        return self.machine.state

    # -- physical actions -----------------------------------------------------

    def move_carriage_to(self, target: int, on_progress: Callable[[int], None] | None = None) -> None:
        """Drives the carriage towards the destination, publishing carriage
        position along the way. Raises [JamError] when the scenario jams."""
        self.machine.transition(MachineState.MOVING)
        try:
            for position in self.carriage.move_to(target):
                on_progress(position) if on_progress else None
        except JamError:
            self.machine.transition(MachineState.JAMMED)
            raise
        self.machine.transition(MachineState.POSITIONED)

    def reach_deposit_ready(self) -> None:
        self.machine.transition(MachineState.READY_FOR_DEPOSIT)

    def start_detect(self) -> None:
        self.machine.transition(MachineState.DETECTING)

    def start_measuring(self) -> None:
        self.machine.transition(MachineState.MEASURING)

    def confirm_deposit(self) -> None:
        self.machine.transition(MachineState.DEPOSIT_CONFIRMED)

    def reset(self) -> None:
        self.machine.transition(MachineState.RESETTING)
        self.machine.transition(MachineState.IDLE)

    def force_error(self, state: MachineState) -> None:
        self.machine.transition(state)

    def snapshot(self) -> dict:
        return {
            "station_id": "station",
            "state": self.machine.state.value,
            "carriage_position": self.carriage.current_position,
            "current_position": self.carriage.current_position,
            "door_state": "CLOSED",
            "weight_grams": round(self.load_cell.read_weight(), 2),
            "weight_stable": False,
            "beam_broken": self.beam.broken,
        }


def realtime_sleep(seconds: float) -> None:
    time.sleep(max(0.0, seconds))