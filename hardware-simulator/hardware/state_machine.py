"""Explicit hardware state machine with a strict transition table.

States                    Transitions
IDLE                     -> ROUTING
ROUTING                  -> MOVING
MOVING                   -> POSITIONED | JAMMED | WRONG_POSITION | TIMEOUT | SENSOR_ERROR
POSITIONED               -> READY_FOR_DEPOSIT | JAMMED | WRONG_POSITION
READY_FOR_DEPOSIT        -> DETECTING
DETECTING                -> MEASURING | SENSOR_ERROR
MEASURING                -> DEPOSIT_CONFIRMED | UNDERWEIGHT | SENSOR_ERROR
DEPOSIT_CONFIRMED        -> RESETTING
JAMMED / WRONG_POSITION / UNDERWEIGHT / SENSOR_ERROR / TIMEOUT -> RESETTING
RESETTING                -> IDLE

Any other transition raises [IllegalTransition] — the machine is the single
authoritative source of valid sequences (mirrors ESP32 firmware behaviour).
"""
from __future__ import annotations

from enum import Enum


class MachineState(Enum):
    IDLE = "IDLE"
    ROUTING = "ROUTING"
    MOVING = "MOVING"
    POSITIONED = "POSITIONED"
    READY_FOR_DEPOSIT = "READY_FOR_DEPOSIT"
    DETECTING = "DETECTING"
    MEASURING = "MEASURING"
    DEPOSIT_CONFIRMED = "DEPOSIT_CONFIRMED"
    RESETTING = "RESETTING"
    JAMMED = "JAMMED"
    WRONG_POSITION = "WRONG_POSITION"
    UNDERWEIGHT = "UNDERWEIGHT"
    SENSOR_ERROR = "SENSOR_ERROR"
    TIMEOUT = "TIMEOUT"


_ERROR_STATES = {
    MachineState.JAMMED,
    MachineState.WRONG_POSITION,
    MachineState.UNDERWEIGHT,
    MachineState.SENSOR_ERROR,
    MachineState.TIMEOUT,
}

_TRANSITIONS: dict[MachineState, set[MachineState]] = {
    MachineState.IDLE: {MachineState.ROUTING},
    MachineState.ROUTING: {MachineState.MOVING},
    MachineState.MOVING: {
        MachineState.POSITIONED,
        MachineState.JAMMED,
        MachineState.WRONG_POSITION,
        MachineState.TIMEOUT,
        MachineState.SENSOR_ERROR,
    },
    MachineState.POSITIONED: {
        MachineState.READY_FOR_DEPOSIT,
        MachineState.JAMMED,
        MachineState.WRONG_POSITION,
    },
    MachineState.READY_FOR_DEPOSIT: {MachineState.DETECTING},
    MachineState.DETECTING: {MachineState.MEASURING, MachineState.SENSOR_ERROR},
    MachineState.MEASURING: {
        MachineState.DEPOSIT_CONFIRMED,
        MachineState.UNDERWEIGHT,
        MachineState.SENSOR_ERROR,
    },
    MachineState.DEPOSIT_CONFIRMED: {MachineState.RESETTING},
    MachineState.RESETTING: {MachineState.IDLE},
}

for _error in _ERROR_STATES:
    _TRANSITIONS.setdefault(_error, set()).add(MachineState.RESETTING)


class IllegalTransition(RuntimeError):
    pass


class StateMachine:
    def __init__(self) -> None:
        self._state = MachineState.IDLE

    @property
    def state(self) -> MachineState:
        return self._state

    def transition(self, new_state: MachineState) -> MachineState:
        allowed = _TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise IllegalTransition(
                f"illegal transition {self._state.value} -> {new_state.value}"
            )
        self._state = new_state
        return self._state

    def can_transition(self, new_state: MachineState) -> bool:
        return new_state in _TRANSITIONS.get(self._state, set())

    def in_error(self) -> bool:
        return self._state in _ERROR_STATES