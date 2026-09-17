"""SCWT student-handoff QR flow.

The student app mints a short-lived single-use handoff token
(POST /deposit/handoff-token); the STATION tablet scans the QR and claims a
capture-first deposit session with its station key
(POST /deposit/session/claim). Single-use + short TTL => non-replayable.
"""
from __future__ import annotations

from app.models.auth_token import hash_token


def _auth_header(client, token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_handoff_token_requires_auth(client):
    r = client.post("/api/v1/deposit/handoff-token")
    assert r.status_code == 401


def test_claim_requires_station_key(client):
    r = client.post("/api/v1/deposit/session/claim", json={"token": "x" * 40})
    assert r.status_code == 401


def test_full_handoff_flow_creates_capture_session(client):
    register = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Handoff Student",
            "email": "handoff@example.com",
            "password": "secret123",
            "facultyId": "ENGINEERING",
        },
    )
    assert register.status_code == 201, register.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "handoff@example.com", "password": "secret123"},
    )
    token = login.json()["token"]

    mint = client.post(
        "/api/v1/deposit/handoff-token", headers=_auth_header(client, token)
    )
    assert mint.status_code == 200, mint.text
    body = mint.json()
    assert body["token"] and len(body["token"]) >= 32
    assert body["expires_at"]

    claim = client.post(
        "/api/v1/deposit/session/claim",
        headers={"X-Station-Key": "scwt-dev-station-key"},
        json={"token": body["token"], "station_id": "st-001"},
    )
    assert claim.status_code == 200, claim.text
    session = claim.json()
    assert session["status"] in ("capture",)
    assert session["station_id"] == "st-001"
    assert session["operation_id"].startswith("OP-")


def test_handoff_token_is_single_use(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Reuse Student",
            "email": "reuse@example.com",
            "password": "secret123",
            "facultyId": "ENGINEERING",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "reuse@example.com", "password": "secret123"},
    )
    token = login.json()["token"]
    mint = client.post("/api/v1/deposit/handoff-token", headers=_auth_header(client, token))
    raw = mint.json()["token"]

    first = client.post(
        "/api/v1/deposit/session/claim",
        headers={"X-Station-Key": "scwt-dev-station-key"},
        json={"token": raw, "station_id": "st-001"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/deposit/session/claim",
        headers={"X-Station-Key": "scwt-dev-station-key"},
        json={"token": raw, "station_id": "st-001"},
    )
    assert second.status_code == 422
    assert second.json()["code"] == "INVALID_HANDOFF_TOKEN"


def test_unknown_token_rejected(client):
    r = client.post(
        "/api/v1/deposit/session/claim",
        headers={"X-Station-Key": "scwt-dev-station-key"},
        json={"token": "a" * 40, "station_id": "st-001"},
    )
    assert r.status_code == 422


def test_expired_token_rejected(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Expiry Student",
            "email": "expiry@example.com",
            "password": "secret123",
            "facultyId": "ENGINEERING",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "expiry@example.com", "password": "secret123"},
    )
    token = login.json()["token"]
    mint = client.post("/api/v1/deposit/handoff-token", headers=_auth_header(client, token))
    raw = mint.json()["token"]
    # Backdate the stored token past its TTL.
    from datetime import datetime, timedelta, timezone

    from app.database import SessionLocal
    from app.models import AuthToken

    hashed = hash_token(raw)
    with SessionLocal() as db:
        rec = (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hashed, AuthToken.purpose == "deposit_handoff")
            .first()
        )
        assert rec is not None
        rec.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    r = client.post(
        "/api/v1/deposit/session/claim",
        headers={"X-Station-Key": "scwt-dev-station-key"},
        json={"token": raw, "station_id": "st-001"},
    )
    assert r.status_code == 422


def test_stations_expose_mechanism_and_neutral_position(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Stations Student",
            "email": "stations@example.com",
            "password": "secret123",
            "facultyId": "ENGINEERING",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "stations@example.com", "password": "secret123"},
    )
    r = client.get(
        "/api/v1/stations", headers=_auth_header(client, login.json()["token"])
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "seeded stations expected"
    for st in items:
        assert st["mechanism"] == "carriage"
        assert "carriage_position" in st


def test_active_deposit_found_after_claim(client):
    """After a station claims the handoff QR, GET /deposit/active exposes the
    live session to the student (who never saw the claim response)."""
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Active Student",
            "email": "active@example.com",
            "password": "secret123",
            "facultyId": "ENGINEERING",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "active@example.com", "password": "secret123"},
    )
    token = login.json()["token"]
    mint = client.post("/api/v1/deposit/handoff-token", headers=_auth_header(client, token))
    raw = mint.json()["token"]
    claim = client.post(
        "/api/v1/deposit/session/claim",
        headers={"X-Station-Key": "scwt-dev-station-key"},
        json={"token": raw, "station_id": "st-001"},
    )
    assert claim.status_code == 200
    op_id = claim.json()["operation_id"]

    r = client.get("/api/v1/deposit/active", headers=_auth_header(client, token))
    assert r.status_code == 200, r.text
    dep = r.json()["deposit"]
    assert dep["operation_id"] == op_id
    assert dep["status"] == "capture"


def test_active_deposit_404_when_idle(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Idle Student",
            "email": "idle@example.com",
            "password": "secret123",
            "facultyId": "ENGINEERING",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "idle@example.com", "password": "secret123"},
    )
    r = client.get("/api/v1/deposit/active", headers=_auth_header(client, login.json()["token"]))
    assert r.status_code == 404


def test_active_deposit_requires_auth(client):
    assert client.get("/api/v1/deposit/active").status_code == 401
