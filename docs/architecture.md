# SCWT Architecture

```
                SCWT  (this repository)
   ┌──────────────┼──────────────────┐
   │              │                  │
  mobile         FastAPI +        AI service
  (student app)  PostgreSQL       (station camera → classify → route)
        └──────────┬──────────────────┘
                   │ MQTT (scwt/stations/#)
                   ▼
        CARRIAGE Station (firmware / simulator)
```

## Components

| Component | Port (dev) | Role |
|---|---|---|
| `mobile/` | — | Flutter student app (`scwt_flutter`); the ONLY client |
| `web/` | 3000 | Next.js UI prototype of the app experience |
| `backend/` | API 8100 | FastAPI: auth, deposits, points authority, rewards, leaderboard, handoff QR |
| `ai-service/` | 8052 | quality gate → preprocessing → ONNX classifier → confidence policy |
| `hardware-simulator/` | — | MQTT-accurate carriage station simulator (the future ESP32) |
| `firmware/carriage-v1/` | — | ESP32 firmware skeleton for the physical station |
| mosquitto | 1886 | authenticated broker, least-privilege ACL (`infra/mosquitto/`) |
| PostgreSQL | 55432 (compose) | system of record; Alembic owns the schema |

## Deposit flow (authority model)

1. The app uploads a capture (`POST /api/v1/ai/predict` with the camera
   frame) — the backend forwards it to the AI service; the app NEVER
   classifies locally and NEVER computes points.
2. `POST /api/v1/deposit/session` — the backend publishes the `route`
   command on `scwt/stations/{code}/command` with an `operation_id`.
3. The station (simulator/firmware) executes the deposit: drives the carriage
   along the rail to the routed compartment, releases the item, weighs it on
   the in-carriage load cell.
4. The station publishes machine states plus a terminal `deposit_result`
   (`actual_position`, `carriage_position`, weight, stability, beam, mech).
5. The backend validates EVERY gate independently and — only then — awards
   points in one transaction. A machine may believe it succeeded and still
   be rejected (`wrong_position`, `underweight`, `jam`, …).

## Trust boundaries

- **Points authority lives in the backend only.** Balances and history come
  exclusively from the API; deposits complete only via validated physical
  events on SCWT's own MQTT infrastructure.
- **The student app never touches MQTT.** Broker credentials never leave the
  server side; the app talks HTTPS + deposit WebSocket only.
- **The broker is authenticated even in development** (least-privilege ACL,
  see `infra/mosquitto/acl`).
- The AI service is reached ONLY by the backend (never by clients).

## Service topology (development)

`scripts/dev_up.sh` starts the full real stack locally (broker → AI →
backend) with per-run broker credentials; `scripts/dev_health.sh` verifies
every service including a real prediction round-trip.
`infra/docker-compose.yml` runs the same stack containerised.
