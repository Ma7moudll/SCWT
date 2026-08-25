# Ecolamp

**Ecolamp — Recycle Today, Save Tomorrow.**
A standalone campus waste-sorting product built around a **Carriage-based
sorting station**: a carriage travels along a linear rail and releases
classified waste into the correct bin.

```
                ECOLAMP  (this repository)
   ┌──────────────┼──────────────────┐
   │              │                  │
 Flutter       FastAPI +        AI service
 Student App   PostgreSQL       (station camera → classify → route)
        └──────────┬──────────────────┘
                   │ MQTT (ecolamp/stations/#)
                   ▼
          CARRIAGE Station (ESP32 / simulator)
```

This repository contains the **entire product**: student app, backend,
database schema, AI pipeline, MQTT infrastructure, carriage simulator and
firmware, tests, and end-to-end proofs. It runs with no dependency on any
other project's source or services.

## Layout

| Path | What |
|---|---|
| `lib/` `test/` | Flutter student app (demo mode + production API client) |
| `backend/` | FastAPI + SQLAlchemy + Alembic; authentication, points authority, deposits, rewards, leaderboard, handoff QR |
| `ai-service/` | Station-side classifier (quality gate → preprocess → ONNX model → confidence policy) |
| `hardware-simulator/` | Carriage ESP32 simulator speaking the station MQTT contract |
| `firmware/carriage-v1/` | ESP32 firmware skeleton for the physical carriage station |
| `scripts/` | `e2e_carriage_chain.py` — full-stack live proof |
| `infra/` | broker config; `docker-compose.yml` dev stack (API 8100 · AI 8052 · MQTT 1886) |
| `docs/backend-api-contract.md` | the public contract the app consumes |

## The Carriage mechanism

One station body, four compartments at fixed positions on a linear rail.
The carriage carries the deposited item from the intake to the routed bin:

```
ROUTE_TO compartment 2 → lookup rail position → stepper drives belt
→ limit-switch homing on boot → position confirmed → item released
→ in-carriage load cell weighed the deposit → deposit_result published
```

Trade-offs vs other sorting mechanisms: simplest motion control and manual
clearing, one moving axis, per-item weighing happens naturally inside the
carriage; worst-case travel is longer than a rotary chute of the same
footprint.

## Modes

- **Demo** (default): fully local app experience — local session, points,
  history, simulated deposit chain. No backend required.
- **Production**: the app talks to THIS repository's backend.

```bash
flutter run --dart-define=ECOLAMP_MODE=production \
            --dart-define=API_BASE_URL=http://10.0.2.2:8100/api/v1
# release builds require https:// API_BASE_URL
```

Points authority: in production the client NEVER computes points. Balances
and history come exclusively from the backend; deposits complete only via
validated physical events on Ecolamp's own MQTT infrastructure.

## Run the full stack

```bash
docker compose up                       # db + mqtt + ai + backend
# or manually: see backend/README steps in docs/
python scripts/e2e_carriage_chain.py    # live full-chain proof (49 checks)
```

## Develop & test

```bash
flutter pub get && flutter analyze && flutter test
flutter build apk --release

cd backend   && pip install -r requirements.txt && alembic upgrade head && pytest
cd ai-service && pip install -r requirements.txt && pytest
cd hardware-simulator && pytest
pio run -d firmware/carriage-v1
```

Ports are owned by this project (8100 / 8052 / 1886) so it can run side by
side with any other software on the same machine.
