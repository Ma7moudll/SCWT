"""Scenario definitions for the hardware simulator.

Each scenario produces a precise physical event sequence (carriage move,
weight ramp, beam, mechanical confirmation) — identical to what the real ESP32
would report. The backend decides validity; the simulator never declares
"success" itself.

Scenario                       Behaviour                               Backend outcome
---------------------------------------------------------------------------------------------
valid-plastic (default)         route as told, 18.4g stable,             CONFIRMED +5 pts
                                beam break -> clear, mech confirm
wrong-position                  carriage reaches compartment 2 while     REJECTED (wrong_position)
                                backend expected 1
underweight                     route ok but only 0.5g reservoir         REJECTED (underweight)
jam                             carriage jams mid-move                  REJECTED (jam)
timeout                         completes everything AFTER the session   REJECTED (expired)
                                expiry (slow machine)
duplicate                       emits two identical terminal events      first CONFIRMED,
                                for the same operation_id                second REJECTED (dup)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DepositPlan:
    name: str = "valid-plastic"
    destination_position: int | None = None  # None -> obey backend routing
    actual_position: int | None = None  # overrides destination (wrong-position)
    weight_timeline: list[tuple[float, float]] = field(
        default_factory=lambda: [(0.0, 0.0), (0.8, 4.0), (1.4, 12.0), (2.0, 18.4)]
    )
    final_weight: float | None = None  # overrides final reading (underweight)
    beam_seen: bool = True
    mechanical_confirmed: bool = True
    jam_at_step: int | None = None      # V1 carriage: 1-based step index
    delay_before_terminal: float = 0.0
    duplicate_terminal: bool = False
    emit_machine_status: str = "confirmed"  # what the machine believes happened


SCENARIOS: dict[str, DepositPlan] = {
    "valid-plastic": DepositPlan(name="valid-plastic"),
    "wrong-position": DepositPlan(
        name="wrong-position",
        destination_position=2,
        actual_position=2,
    ),
    "underweight": DepositPlan(
        name="underweight",
        weight_timeline=[(0.0, 0.0), (0.8, 0.3), (1.4, 0.5)],
        final_weight=0.5,
        emit_machine_status="underweight",
    ),
    "jam": DepositPlan(
        name="jam",
        destination_position=2,  # force a real carriage move so it can jam
        jam_at_step=1,
        emit_machine_status="jam",
    ),
    "timeout": DepositPlan(name="timeout", delay_before_terminal=320.0),
    "duplicate": DepositPlan(name="duplicate", duplicate_terminal=True),
}


def get_scenario(name: str) -> DepositPlan:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; choose from {sorted(SCENARIOS)}")
    return SCENARIOS[name]