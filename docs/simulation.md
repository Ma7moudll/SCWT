# Hardware Protocol & Simulator

## What is simulated

Only the **hardware itself** is simulated. Everything else — MQTT, the broker,
the backend, Postgres, the AI service, points — is real. The simulator is the
future ESP32 firmware: it subscribes to `…/{code}/command`, drives (simulated)
actuators/sensors, and publishes the documented telemetry. Replacing it with
real firmware requires **zero backend changes**.

Components in `hardware-simulator/`:

| Module | What it models |
|---|---|
| `config.py` | env-driven physical parameters (movement time, noise, thresholds) |
| `hardware/carriage.py` | carriage that moves position-by-position; configurable jam |
| `hardware/load_cell.py` | HX711-like load cell; deterministic settle profile + gaussian noise |
| `hardware/sensors.py` | IR beam, position and door sensors |
| `hardware/state_machine.py` | strict transition table (`IllegalTransition` on invalid moves) |
| `hardware/station.py` | one station unit (motor + sensors + machine) |
| `scenarios.py` | deterministic deposit plans (see mqtt-contract) |
| `mqtt_client.py` | paho wrapper, protocol-identical to ESP32 code |
| `simulator.py` | runtime + CLI that turns a plan into published telemetry |

The load cell settle profile is a piecewise ADC trace:
`0.0s → 0g, 0.8s → 4g, 1.4s → 12g, 2.0s → 18.4g (stable)`.

## Running it

```bash
# with the dev stack up (scripts/dev_up.sh, broker on :1886):
PYTHONPATH=hardware-simulator python hardware-simulator/simulator.py \
    --scenario valid-plastic
```

Every scenario produces a precise physical event sequence identical to what
the real ESP32 would report; the backend decides validity. Scenarios are
listed in `docs/mqtt-contract.md`.

## Tests

```bash
cd hardware-simulator && pytest
```
