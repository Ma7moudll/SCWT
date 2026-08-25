"""Shared fixtures for backend tests.

Tests run on a throwaway SQLite file (DATABASE_URL env is set BEFORE any app
module import, because `app.config.Settings` is lru_cached). A session-scoped
TestClient exercises the real lifespan; each test gets a clean schema + seed.
"""
from __future__ import annotations

import os
import tempfile

_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.name}"
os.environ["MQTT_BROKER_HOST"] = "127.0.0.1"
os.environ["MQTT_BROKER_PORT"] = "1884"  # nothing listens here; gateway retries quietly
# Integration tests spin up an AUTHENTICATED broker on 1884 with these exact
# credentials (test-only values, never used outside the throwaway broker).
os.environ["MQTT_USERNAME"] = "backend"
os.environ["MQTT_PASSWORD"] = "itest-broker-pass"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_ON_STARTUP"] = "true"
os.environ["SEED_DEMO_USER"] = "true"
os.environ["AUTOMATIC_ROUTING_REQUIRED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, create_tables, drop_all  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ai_client import AiExternalPrediction  # noqa: E402
from app.services.predict_service import PredictService  # noqa: E402
from app.services.seed import seed  # noqa: E402

DEMO_EMAIL = "demo@ecolamp.campus"
DEMO_PASSWORD = "demo123"
STATION_ID = "st-001"
STATION_CODE = "ST-001"


class FakeAi:
    """Deterministic stand-in for the AI service (never reaches HTTP)."""

    def __init__(self, predicted_class: str = "plastic", confidence: float = 0.95, model: str = "development"):
        self.predicted_class = predicted_class
        self.confidence = confidence
        self.model = model

    def predict(self, image_bytes: bytes, content_type: str = "image/jpeg") -> AiExternalPrediction:
        return AiExternalPrediction(self.predicted_class, self.confidence, self.model)


class FakePublisher:
    """Records route/capture commands instead of talking to MQTT."""

    def __init__(self) -> None:
        self.commands: list[dict] = []
        self.capture_requests: list[dict] = []

    def publish_route(self, station_id: str, operation_id: str, destination_position: int, mode: str) -> None:
        self.commands.append(
            {
                "station_id": station_id,
                "operation_id": operation_id,
                "destination_position": destination_position,
                "mode": mode,
            }
        )

    def publish_capture_request(self, station_id: str, operation_id: str) -> None:
        self.capture_requests.append(
            {"station_id": station_id, "operation_id": operation_id}
        )


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_db(client):
    """Clean schema + seed before every test (the MQTT gateway daemon keeps
    retrying 127.0.0.1:1884 harmlessly in the background)."""
    from app.routers import auth as auth_router
    from app.security import revocation as revocation_module

    drop_all()
    create_tables()
    with SessionLocal() as db:
        seed(db, seed_demo_user=True)
    # In-memory security state must not leak between tests.
    auth_router._login_limiter.reset()
    auth_router._register_limiter.reset()
    auth_router._forgot_limiter.reset()
    auth_router._reset_limiter.reset()
    auth_router._verify_limiter.reset()
    revocation_module.revocations.reset()
    yield


@pytest.fixture
def demo_session(client) -> str:
    r = client.post("/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def auth(demo_session) -> dict:
    return {"Authorization": f"Bearer {demo_session}"}


@pytest.fixture
def publisher(monkeypatch):
    from app.routers import deposit as deposit_router

    fp = FakePublisher()
    monkeypatch.setattr(deposit_router, "_publisher", fp)
    return fp


def register_and_login(client, email: str, password: str = "secret99") -> dict:
    """Registration creates the account only (no token since the
    no-auto-login contract); an explicit login establishes the session."""
    r = client.post(
        "/api/v1/auth/register",
        json={"name": email.split("@")[0], "email": email, "facultyId": "ENGINEERING",
              "password": password},
    )
    assert r.status_code == 201, r.text
    assert "token" not in r.json()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _predict(client, token: str, fake_ai: FakeAi, monkeypatch) -> dict:
    """Runs the real API /ai/predict with a stubbed AI service."""
    from app.routers import ai as ai_router

    monkeypatch.setattr(ai_router, "PredictService", lambda: PredictService(ai=fake_ai))
    r = client.post(
        "/api/v1/ai/predict",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("capture.jpg", b"fake-jpeg-bytes", "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def plastic_prediction(client, demo_session, monkeypatch) -> dict:
    return _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)


@pytest.fixture
def metal_prediction(client, demo_session, monkeypatch) -> dict:
    return _predict(client, demo_session, FakeAi("metal", 0.91), monkeypatch)


def confirm_event(operation_id: str, *, status="confirmed", position=1, weight=18.4,
                  stable=True, beam=True, mech=True, carriage=1, station=STATION_ID,
                  extra_fields=None) -> dict:
    event = {
        "station_id": station,
        "operation_id": operation_id,
        "event": "deposit_result",
        "status": status,
        "actual_position": position,
        # V1 carriage firmware reports `carriage_position`; V2 rotary firmware
        # reports the mechanism-neutral `mechanism_position` (see test_rotary_v2).
        "carriage_position": carriage,
        "weight_grams": weight,
        "weight_stable": stable,
        "beam_event_seen": beam,
        "mechanical_confirmed": mech,
    }
    if extra_fields:
        event.update(extra_fields)
    return event