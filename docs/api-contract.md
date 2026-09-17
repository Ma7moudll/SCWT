# SCWT Backend API Contract (client-facing)

SCWT is a **standalone product**: the Flutter app talks ONLY to the
**SCWT Backend** (FastAPI, shipped in this repository under `backend/`).
There is no dependency on any other project's source, database, broker, or AI
service — communication is exclusively this HTTPS contract plus the
deposit WebSocket.

Base URL: `http://<host>:8100` (dev) · prefix `/api/v1`.
Auth: `Authorization: Bearer <jwt>` on everything except register/login.
Timestamps: ISO-8601. Release app builds require an HTTPS `API_BASE_URL`.

## Auth

| Method | Path | Body | Success | Errors |
|---|---|---|---|---|
| POST | `/auth/register` | `{name, email, studentCode?, facultyId, password}` | `201 {user}` (no token) | 409 duplicate email, 422 invalid faculty |
| POST | `/auth/login` | `{email, password}` | `200 {token, user}` | 401 bad credentials, 403 deactivated/unverified |
| POST | `/auth/logout` | — | `{status:"logged_out"}` | 401 |
| GET | `/auth/me` | — | `{user}` | 401 |

`user`: `{id, studentCode, name, facultyId, facultyName, points, avatarVersion, role}`

## Deposits

| Method | Path | Body / headers | Success | Errors |
|---|---|---|---|---|
| POST | `/deposit/handoff-token` | student JWT | `200 {token, expires_at}` (~120 s, single-use) | 401 |
| POST | `/deposit/session/claim` | `{token, station_id}` + `X-Station-Key` header | `200 {deposit}` (`status:"capture"`) | 401 bad key, 422 invalid/expired/replayed QR |
| GET | `/deposit/active` | student JWT | `{deposit}` or 404 when idle | 401 |
| GET | `/deposit/{operation_id}` | student JWT | `{deposit}` | 404 |
| POST | `/deposit/{operation_id}/cancel` | student JWT | `{deposit}` | 404, 422 terminal |
| POST | `/deposit/capture` | multipart `image`,`operation_id`,`station_code` + `X-Station-Key` | `{deposit}` (`analyzing`→routed) | 401 key, 413 size, 422 `{code,error}` gate reject, 503 `{code:"AI_UNAVAILABLE"}` |
| POST | `/deposit/callback/event` | `CallbackEvent` + `X-Station-Key` | validation result | 401 key, 409 duplicate, 404 |

### Deposit wire shape

```json
{"operation_id":"OP-20260825-000001","prediction_id":"","station_id":"st-001",
 "predicted_class":"plastic","expected_position":1,"confidence":0.93,
 "confidence_level":"high","actual_position":1,"weight_g":18.4,
 "mechanical_confirmed":true,"potential_points":5,"points_awarded":5,
 "status":"confirmed","expires_at":"…","reject_reason":null}
```

`status` enum: `capture → analyzing → pending? → routing → moving → ready →
detecting → measuring → confirmed | rejected | cancelled | expired`.
Only terminal states carry points; **only the backend awards points**
(validated physical MQTT events inside its own infrastructure).

### Student handoff QR (contract)

Payload rendered by the app: `SCWT:HANDOFF:<token>`. The token is
short-lived (~120 s), single-use (atomic consumption), worthless without the
station's `X-Station-Key`. No long-lived secrets ever enter a QR.

## User data

| Method | Path | Success |
|---|---|---|
| GET | `/users/me` | `{user}` |
| GET | `/waste/history` | `{items:[{id, operation_id, station_id, predicted_class, weight_g, points_awarded, created_at}]}` |
| GET | `/waste/history/{id}` | `{item}` |
| GET | `/impact` | `{total_points, recycled_kg, items_recycled, co2_saved_kg, breakdown[]}` |
| GET | `/leaderboard/students` · `/leaderboard/faculties` | `{entries:[{id,name,detail,points}]}` |
| GET | `/challenges` | `{items}` |

## Rewards

| Method | Path | Notes |
|---|---|---|
| GET | `/rewards` | `{balance, rewards[]}` |
| GET | `/rewards/redemptions` | caller's redemptions |
| POST | `/rewards/{reward_id}/redeem` | atomic balance deduction; 409 insufficient |
| POST | `/rewards/redemptions/{id}/cancel` | refunds unused code redemptions |

## Stations & real-time

| Method | Path | Success |
|---|---|---|
| GET | `/stations` | `{items:[{id, station_code, name, status, mechanism, carriage_position, state, …}]}` |
| GET | `/stations/{id}` · `/stations/{id}/status` | live snapshot |

`WS /ws/deposits/{operation_id}?token=<jwt>` — frames: `subscribed`, `state`,
`terminal`, `keepalive`. Transport only: the socket carries backend-persisted
state and can never award points. Clients fall back to polling
`GET /deposit/{operation_id}`.

## Error envelope

Server errors use `{"error": "<friendly sentence>"}` (or FastAPI
`{"detail": ...}`); structured capture rejects add `{code, error}` with codes
like `NO_OBJECT`, `LOW_QUALITY`, `CORRUPT_IMAGE`, `INVALID_HANDOFF_TOKEN`.
Status codes: 400/401/403/404/409/413/422/429/5xx.
