# SCWT Station — Mechanical Abstraction (Carriage V1)

> **One product. One domain model. One backend authority. One AI pipeline.
> One physical sorting mechanism: the Carriage on a linear rail.**

The station-level software contract is deliberately mechanism-agnostic. The
carriage is a hardware implementation detail: nothing in the student
experience or the shared domain depends on how the unit moves the waste.

## The contract the mechanism implements

A station unit:

1. **Receives intent** on `scwt/stations/{code}/command`:
   `{"command": "route", "operation_id": "OP-…",
     "destination_position": 2, "mode": "automatic|manual"}`
   plus `{"command": "capture_request", "operation_id": "OP-…"}`.
2. **Executes it mechanically** (implementation detail): determine target
   rail position → drive the stepper position-by-position → limit-switch
   homing on boot → position confirmed → release waste.
3. **Reports physics, never success**: machine states and a terminal
   `deposit_result` event (`actual_position`, `carriage_position`,
   `weight_grams`, `weight_stable`, `beam_event_seen`,
   `mechanical_confirmed`).
4. The **backend independently validates** the physics and — only then —
   awards points in one transaction.

## Where each concept lives

| Concept | Location | Mechanism-aware? |
|---|---|---|
| Route command (compartment intent) | backend MQTT publisher | NO |
| Deposit validation (position/weight/beam) | backend `deposit_service` | NO |
| Station registry telemetry | `station_registry` (internal) | internal only |
| Mechanical execution | firmware / simulator | YES — isolated here |
| Student app vocabulary | SCWT screens | NEVER |

## Rules enforced by audit

- `carriage|stepper|motor|servo|belt|rail` vocabulary must not appear in:
  student domain models, points logic, history, rewards, leaderboard, generic
  deposit API, generic station UI.
- The student app speaks only student language (deposit, compartment,
  points); mechanical vocabulary lives exclusively in the unit's
  controller/firmware and the simulator.
