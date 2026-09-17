# MQTT Contract

Prefix: `scwt/stations` (configurable via `MQTT_TOPIC_PREFIX`).
A single station = one physical unit with **four fixed compartments** on a
linear rail (positions `1..4`), an internal carriage, a load cell and an IR
beam.

## Topics

| Topic | Direction | QoS | Payload |
|---|---|---|---|
| `scwt/stations/{code}/command` | backend → station | 1 | route command |
| `scwt/stations/{code}/state` | station → backend | 1 | machine state changes |
| `scwt/stations/{code}/sensor` | station → backend | 1 | sensor telemetry stream |
| `scwt/stations/{code}/event` | station → backend | 1 | state_changed + terminal `deposit_result` |
| `scwt/stations/{code}/heartbeat` | station → backend | 0 | liveness |

`{code}` is the human station code (`ST-001`).

## Route command (backend → station)

```json
{"command": "route", "operation_id": "OP-…",
 "destination_position": 2, "mode": "automatic|manual"}
```

`mode=manual` records that a human chose the compartment; validation is
identical. A `capture_request` command asks the station camera to upload a
frame to `POST /api/v1/deposit/capture`.

## Physical events

The station reports **physics, never success**: state transitions, per-step
sensor telemetry (`carriage_position`), weight ramp, beam events and a
terminal `deposit_result`:

```json
{"event": "deposit_result", "status": "confirmed|jam|underweight|…",
 "actual_position": 2, "carriage_position": 2,
 "weight_grams": 18.4, "weight_stable": true,
 "beam_event_seen": true, "mechanical_confirmed": true}
```

The backend validates every gate independently (`wrong_position`,
`underweight`, weight instability, missed beam, missing mechanical
confirmation, jam, expired session, duplicate terminal). Only a fully valid
event moves points — in one transaction.

## Machine states

`IDLE → ROUTING → MOVING → POSITIONED → READY_FOR_DEPOSIT → DETECTING →
MEASURING → DEPOSIT_CONFIRMED → RESETTING → IDLE`

Error states (each → `RESETTING`): `JAMMED`, `WRONG_POSITION`, `UNDERWEIGHT`,
`SENSOR_ERROR`, `TIMEOUT`.

State changes are published as `{"event": "state_changed", "state": "…"}`
on `event`. The backend persists the live phase onto the deposit and
forwards the authoritative serialized deposit to the operation's WebSocket
subscribers. The transition is monotonic — a late telemetry frame can never
regress the status — and no state change ever touches points.

## Security

- `allow_anonymous false`; per-identity ACL (`infra/mosquitto/acl`).
- `backend` identity: readwrite on `scwt/stations/#`.
- `station-ST-…` identities: own command topics read, own telemetry write.
- The student app has NO broker credentials and no MQTT access.

## Scenarios shipped with the simulator

| Scenario | Behavior | Backend outcome |
|---|---|---|
| `valid-plastic` | obey route, 18.4g stable, beam+mech OK | confirmed +5 |
| `wrong-position` | carriage stops at compartment 2 (routed to 1) | rejected `wrong_position` |
| `underweight` | only 0.5g | rejected `underweight` |
| `jam` | carriage jams mid-move | rejected `jam` |
| `timeout` | terminal arrives after session expiry | rejected `expired` |
| `duplicate` | two identical terminals | 1st confirmed, 2nd `409` |
