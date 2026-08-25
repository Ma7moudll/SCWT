"""Carriage, sensors, load cell and state machine unit tests."""
from __future__ import annotations

import pytest

from hardware import (
    BeamSensor,
    Carriage,
    IllegalTransition,
    JamError,
    LoadCell,
    MachineState,
    PositionSensor,
    StateMachine,
    settle_profile,
)


# -- Carriage ------------------------------------------------------------------

class TestCarriage:
    def test_move_to_yields_each_intermediate_position(self):
        c = Carriage(initial_position=1, movement_time_per_step=0)
        positions = list(c.move_to(3))
        assert positions == [2, 3]
        assert c.current_position == 3

    def test_move_backwards(self):
        c = Carriage(initial_position=4, movement_time_per_step=0)
        assert list(c.move_to(1)) == [3, 2, 1]
        assert c.current_position == 1

    def test_no_move_when_already_at_target(self):
        c = Carriage(initial_position=2, movement_time_per_step=0)
        assert list(c.move_to(2)) == []
        assert c.current_position == 2

    def test_jam_raises_and_position_unchanged(self):
        c = Carriage(initial_position=1, movement_time_per_step=0)
        c.jam_at_step = 1
        with pytest.raises(JamError):
            list(c.move_to(3))
        assert c.current_position == 1

    def test_jam_on_later_step(self):
        c = Carriage(initial_position=1, movement_time_per_step=0)
        c.jam_at_step = 2
        with pytest.raises(JamError):
            list(c.move_to(4))
        assert c.current_position == 2  # jammed after the second step


# -- Sensors -------------------------------------------------------------------

class TestSensors:
    def test_beam(self):
        b = BeamSensor()
        assert b.broken is False
        b.set(True)
        assert b.read() is True

    def test_position_sensor_validates(self):
        p = PositionSensor((1, 2, 3, 4), current=1)
        p.set(4)
        assert p.read() == 4
        with pytest.raises(ValueError):
            p.set(9)


# -- Load cell -----------------------------------------------------------------

class TestLoadCell:
    def test_set_value_and_read(self):
        cell = LoadCell(noise_grams=0, seed=1)
        cell.set_value(18.4)
        assert cell.read_weight() == 18.4

    def test_noise_keeps_reading_within_bounds(self):
        cell = LoadCell(noise_grams=0.5, seed=7)
        for _ in range(50):
            cell.set_value(10.0)
            assert -0.5 <= cell.read_weight() - 10.0 <= 0.5

    def test_settle_profile_ramps_between_breakpoints(self):
        ramp = settle_profile([(0.0, 0.0), (0.8, 4.0), (1.4, 12.0), (2.0, 18.4)])
        assert ramp(0.0) == 0.0
        assert ramp(0.4) == 2.0  # midpoint of 0->4 over 0->0.8
        assert ramp(0.8) == 4.0
        assert ramp(2.0) == 18.4
        assert ramp(5.0) == 18.4  # clamped after settle

    def test_profile_is_monotonic(self):
        ramp = settle_profile([(0.0, 0.0), (0.8, 4.0), (1.4, 12.0), (2.0, 18.4)])
        prev = -1
        for t in [i / 10 for i in range(0, 41)]:
            v = ramp(t)
            assert v >= prev
            prev = v


# -- State machine ---------------------------------------------------------------

class TestStateMachine:
    def test_happy_path(self):
        m = StateMachine()
        m.transition(MachineState.ROUTING)
        m.transition(MachineState.MOVING)
        m.transition(MachineState.POSITIONED)
        m.transition(MachineState.READY_FOR_DEPOSIT)
        m.transition(MachineState.DETECTING)
        m.transition(MachineState.MEASURING)
        m.transition(MachineState.DEPOSIT_CONFIRMED)
        m.transition(MachineState.RESETTING)
        m.transition(MachineState.IDLE)
        assert m.state == MachineState.IDLE

    def test_illegal_transition_raises(self):
        m = StateMachine()
        m.transition(MachineState.ROUTING)
        with pytest.raises(IllegalTransition):
            m.transition(MachineState.DEPOSIT_CONFIRMED)  # ROUTING -> DEPOSIT_CONFIRMED

    def test_error_states_can_reset(self):
        # Legal paths to each error state, then RESETTING -> IDLE.
        paths = {
            MachineState.JAMMED: [MachineState.ROUTING, MachineState.MOVING],
            MachineState.WRONG_POSITION: [MachineState.ROUTING, MachineState.MOVING, MachineState.POSITIONED],
            MachineState.UNDERWEIGHT: [
                MachineState.ROUTING, MachineState.MOVING, MachineState.POSITIONED,
                MachineState.READY_FOR_DEPOSIT, MachineState.DETECTING, MachineState.MEASURING,
            ],
            MachineState.SENSOR_ERROR: [MachineState.ROUTING, MachineState.MOVING, MachineState.POSITIONED, MachineState.READY_FOR_DEPOSIT, MachineState.DETECTING],
            MachineState.TIMEOUT: [MachineState.ROUTING, MachineState.MOVING],
        }
        for error_state, prefix in paths.items():
            m = StateMachine()
            for step in prefix:
                m.transition(step)
            m.transition(error_state)
            assert m.in_error()
            m.transition(MachineState.RESETTING)
            m.transition(MachineState.IDLE)

    def test_can_transition(self):
        m = StateMachine()
        assert m.can_transition(MachineState.ROUTING)
        assert not m.can_transition(MachineState.MOVING)
        assert not m.in_error()