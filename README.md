# SCWT

**SCWT — Smart Campus Waste Transformation.**
A standalone campus waste-sorting product built around a **Carriage-based
sorting station**: a carriage travels along a linear rail and releases
classified waste into the correct bin.

```
                SCWT  (this repository)
   ┌──────────────┼──────────────────┐
   │              │                  │
  mobile         FastAPI +        AI service
 (student app)  PostgreSQL       (station camera → classify → route)
        └──────────┬──────────────────┘
                   │ MQTT (scwt/stations/#)
                   ▼
        CARRIAGE Station (ESP32 / simulator)
```

This repository contains the **entire product**: student app, web prototype,
backend, database schema, AI pipeline, MQTT infrastructure, carriage
simulator and firmware, tests, and end-to-end proofs. It runs with no
dependency on any other project's source or services.

## The Carriage mechanism

One station body, four compartments at fixed positions on a linear rail.
The carriage carries the deposited item from the intake to the routed bin:

```
ROUTE_TO compartment 2 → lookup rail position → stepper drives belt
→ limit-switch homing on boot → position confirmed → item released
→ in-carriage load cell weighs the deposit → deposit_result published
```

Trade-offs vs other sorting mechanisms: simplest motion control and manual
clearing, one moving axis, per-item weighing happens naturally inside the
carriage; worst-case travel is longer than a rotary chute of the same
footprint. Engineering notes: `docs/carriage-v1.md`.

## Layout

| Path | What |
|---|---|
| `mobile/` | Flutter student app (`scwt_flutter`; demo mode + production API client) |
| `web/` | Next.js UI prototype of the app experience |
| `backend/` | FastAPI + SQLAlchemy + Alembic; authentication, points authority, deposits, rewards, leaderboard, handoff QR |
| `ai-service/` | Station-side classifier (quality gate → preprocess → ONNX model → confidence policy) |
| `hardware-simulator/` | Carriage ESP32 simulator speaking the station MQTT contract |
| `firmware/carriage-v1/` | ESP32 firmware skeleton for the physical carriage station |
| `scripts/` | `e2e_carriage_chain.py` full-stack live proof · `dev_up.sh` / `dev_health.sh` real dev stack |
| `infra/` | docker-compose dev stack + authenticated mosquitto config (API 8100 · AI 8052 · MQTT 1886) |
| `docs/` | architecture, API contract, MQTT contract, mechanism notes, AI validation, hardware checklist |

## Modes

- **Demo** (default): fully local app experience — local session, points,
  history, simulated deposit chain. No backend required.
- **Production**: the app talks to THIS repository's backend.

```bash
cd mobile && flutter run --dart-define=SCWT_MODE=production \
            --dart-define=API_BASE_URL=http://10.0.2.2:8100/api/v1
# release builds require https:// API_BASE_URL
```

Points authority: in production the client NEVER computes points. Balances
and history come exclusively from the backend; deposits complete only via
validated physical events on SCWT's own MQTT infrastructure.

## Run the full stack

```bash
scripts/dev_up.sh                        # real stack: broker + AI + backend
scripts/dev_health.sh                    # honest health verification
docker compose -f infra/docker-compose.yml up --build   # or containerised
python scripts/e2e_carriage_chain.py     # live full-chain proof
```

## Develop & test

```bash
cd mobile && flutter pub get && flutter analyze && flutter test
flutter build apk --release

cd backend    && pip install -r requirements.txt && alembic upgrade head && pytest
cd ai-service && pip install -r requirements.txt -r requirements-training.txt && pytest
cd hardware-simulator && pytest
pio run -d firmware/carriage-v1
```

Ports are owned by this project (8100 / 8052 / 1886 · PostgreSQL 55432) so it
can run side by side with any other software on the same machine.
