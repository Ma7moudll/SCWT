# Carriage Sorting Mechanism (V1) — engineering notes

SCWT's sorting mechanism is a **carriage on a linear rail**: one station
body, four compartments at fixed positions along the rail, and a carriage
that carries the deposited item from the intake to the routed bin.

## Operation sequence

```
ROUTE_TO compartment 2 → look up rail position (calibration table)
→ stepper drives the belt position-by-position
→ limit-switch homing on boot → position confirmed (position sensor)
→ item released into the compartment
→ in-carriage load cell weighs the deposit → settle profile → stable
→ IR beam across the opening verifies insertion
→ deposit_result published → backend validates → points
```

## Design properties

- **One moving axis** — simplest motion control of the candidate mechanisms;
  a single stepper, a homing switch and a position sensor cover the whole
  kinematics.
- **Per-item weighing happens naturally inside the carriage** — the load
  cell rides with the item, so the weight gate needs no extra hardware.
- **Manual clearing is trivial** — every compartment is reachable by driving
  the carriage; no disassembly.
- **Trade-off** — worst-case travel is longer than a rotary chute of the same
  footprint (the carriage must traverse the rail, not just swing an angle).

## Hardware model (simulator mirrors this)

| Element | Model |
|---|---|
| Rail positions | 4 fixed compartments, positions `1..4` |
| Motion | stepper + belt, `movement_time_per_step`, jam injection per step |
| Homing | limit switch on boot (`home()` before first route) |
| Position feedback | position sensor (drives `carriage_position` on the wire) |
| Weight | HX711-like load cell with deterministic settle profile + gaussian noise |
| Insertion check | IR beam across the station opening |

## Firmware

`firmware/carriage-v1/` is the ESP32 skeleton speaking the exact MQTT
contract (`docs/mqtt-contract.md`): `carriage_controller.h` (motion),
`station_fsm.h` (state machine), `mqtt_station.h` (topics), `config.h`
(calibration constants). Compile with:

```bash
pio run -d firmware/carriage-v1     # compiles clean for esp32dev
```

The simulator (`hardware-simulator/`) is protocol-identical to this firmware:
swapping one for the other requires **zero backend changes**.
