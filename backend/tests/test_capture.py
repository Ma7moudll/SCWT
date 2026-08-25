"""Station-camera capture flow (FINAL architecture).

The station camera — not the phone — is the classification source. A session
is created capture-first (`POST /deposit/session` with no prediction), a
`capture_request` MQTT command tells the camera to snap, and the camera posts
the frame to `POST /deposit/capture` with the shared station key. The backend
classifies with the real AI service, attaches the prediction and routes per
the confidence policy. Points STILL only ever come from the physical MQTT
`deposit_result` event.
"""
from __future__ import annotations

from app.database import SessionLocal
from app.models import AiPrediction, DepositSession, User

STATION_KEY = "ecolamp-dev-station-key"


def install_fake_ai(monkeypatch, fake_ai):
    """Swaps the capture endpoint's DepositService for one that carries a
    stubbed AI service, records commands on a FakePublisher, and wires that
    publisher into the router so assertions can inspect emitted commands."""
    from app.routers import deposit as deposit_router
    from app.services.deposit_service import DepositService
    from app.services.predict_service import PredictService

    from .conftest import FakePublisher

    fp = FakePublisher()
    monkeypatch.setattr(deposit_router, "_publisher", fp)
    monkeypatch.setattr(
        deposit_router, "DepositService",
        lambda pub: DepositService(pub, predictor=PredictService(ai=fake_ai)),
    )
    return fp


def create_capture_session(client, auth) -> dict:
    r = client.post(
        "/api/v1/deposit/session", headers=auth, json={"station_id": "st-001"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def capture(client, operation_id: str, image: bytes = b"fake-frame-jpeg") -> tuple[int, dict]:
    r = client.post(
        "/api/v1/deposit/capture",
        data={"operation_id": operation_id, "station_code": "ST-001"},
        files={"image": ("snap.jpg", image, "image/jpeg")},
        headers={"X-Station-Key": STATION_KEY},
    )
    return r.status_code, r.json()


def demo_user_id() -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.email == "demo@ecolamp.campus").first().id


def user_points(user_id: str) -> int:
    with SessionLocal() as db:
        return db.get(User, user_id).points


def session_row(operation_id: str) -> DepositSession:
    with SessionLocal() as db:
        return db.query(DepositSession).filter(
            DepositSession.operation_id == operation_id
        ).first()


# --------------------------------------------------------------------------
# Session-first create
# --------------------------------------------------------------------------

def test_capture_session_created_without_prediction(client, auth, publisher):
    session = create_capture_session(client, auth)
    assert session["status"] == "capture"
    assert session["prediction_id"] == ""
    assert session["predicted_class"] == ""
    # No route command yet — routing only happens once the frame is classified.
    assert publisher.commands == []
    assert len(publisher.capture_requests) == 1
    req = publisher.capture_requests[0]
    assert req["operation_id"] == session["operation_id"]
    assert req["station_id"] == "ST-001"


def test_capture_session_creation_never_awards_points(client, auth):
    user_id = demo_user_id()
    before = user_points(user_id)
    create_capture_session(client, auth)
    assert user_points(user_id) == before


def test_unknown_station_rejected_for_capture_session(client, auth):
    r = client.post(
        "/api/v1/deposit/session", headers=auth, json={"station_id": "st-999"}
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Capture endpoint: classification + routing
# --------------------------------------------------------------------------

def test_capture_routes_high_confidence(client, auth, monkeypatch):
    from .conftest import FakeAi

    fp = install_fake_ai(monkeypatch, FakeAi("plastic", 0.95))
    session = create_capture_session(client, auth)
    code, result = capture(client, session["operation_id"])
    assert code == 200, result
    assert result["status"] == "pending"
    assert result["predicted_class"] == "plastic"
    assert result["expected_position"] == 1
    assert result["potential_points"] == 5
    # High confidence routes AUTOMATICALLY.
    assert fp.commands, "route command must be published after capture"
    cmd = fp.commands[-1]
    assert cmd["destination_position"] == 1
    assert cmd["mode"] == "automatic"
    # Prediction persisted and attached to the session.
    s = session_row(session["operation_id"])
    assert s.ai_prediction_id is not None
    with SessionLocal() as db:
        assert db.get(AiPrediction, s.ai_prediction_id) is not None


def test_capture_metadata_uses_station_source(client, auth, monkeypatch):
    from .conftest import FakeAi

    install_fake_ai(monkeypatch, FakeAi("paper", 0.92))
    session = create_capture_session(client, auth)
    code, _ = capture(client, session["operation_id"])
    assert code == 200
    s = session_row(session["operation_id"])
    with SessionLocal() as db:
        pred = db.get(AiPrediction, s.ai_prediction_id)
        assert pred.image_url == "station-camera://ST-001"


def test_capture_medium_confidence_manual_routing(client, auth, monkeypatch):
    from .conftest import FakeAi

    fp = install_fake_ai(monkeypatch, FakeAi("plastic", 0.60))
    session = create_capture_session(client, auth)
    code, result = capture(client, session["operation_id"])
    assert code == 200
    assert result["status"] == "pending"
    assert fp.commands[-1]["mode"] == "manual"


def test_capture_low_confidence_rejected_no_route(client, auth, monkeypatch):
    from .conftest import FakeAi

    fp = install_fake_ai(monkeypatch, FakeAi("plastic", 0.40))
    session = create_capture_session(client, auth)
    code, result = capture(client, session["operation_id"])
    assert code == 200
    assert result["status"] == "rejected"
    assert "confidence" in result["reject_reason"].lower()
    assert fp.commands == [], "low confidence must never issue a route command"


def test_capture_gate_rejection_retake(client, auth, monkeypatch):
    from app.services.ai_client import AiGateRejection

    class _Rejecting:
        def predict(self, image_bytes, image_url=None):
            raise AiGateRejection(
                "LOW_QUALITY", "Image quality is too low. Improve lighting."
            )

    fp = install_fake_ai(monkeypatch, _Rejecting())
    session = create_capture_session(client, auth)
    code, body = capture(client, session["operation_id"])
    assert code == 422
    assert body["code"] == "LOW_QUALITY"
    # No prediction row persisted, no session advanced, no routing attempted.
    assert fp.commands == []
    with SessionLocal() as db:
        assert db.query(AiPrediction).count() == 0
        s = db.query(DepositSession).filter(
            DepositSession.operation_id == session["operation_id"]
        ).first()
        assert s.status == "capture", "session stays capture-able for a retake"


def test_capture_requires_station_key(client, auth):
    session = create_capture_session(client, auth)
    r = client.post(
        "/api/v1/deposit/capture",
        data={"operation_id": session["operation_id"], "station_code": "ST-001"},
        files={"image": ("snap.jpg", b"x", "image/jpeg")},
    )
    assert r.status_code == 401


def test_capture_wrong_station_key(client, auth):
    session = create_capture_session(client, auth)
    r = client.post(
        "/api/v1/deposit/capture",
        data={"operation_id": session["operation_id"], "station_code": "ST-001"},
        files={"image": ("snap.jpg", b"x", "image/jpeg")},
        headers={"X-Station-Key": "wrong-key"},
    )
    assert r.status_code == 401


def test_capture_unknown_operation(client, auth):
    code, body = capture(client, "OP-20990101-999999")
    assert code == 422


def test_capture_station_mismatch(client, auth, monkeypatch):
    from .conftest import FakeAi

    install_fake_ai(monkeypatch, FakeAi("plastic", 0.95))
    session = create_capture_session(client, auth)
    r = client.post(
        "/api/v1/deposit/capture",
        data={"operation_id": session["operation_id"], "station_code": "ST-ORPHAN"},
        files={"image": ("snap.jpg", b"frame", "image/jpeg")},
        headers={"X-Station-Key": STATION_KEY},
    )
    assert r.status_code == 422


def test_capture_ai_service_unavailable_503_and_capture_retake(client, auth, monkeypatch):
    """AI outage failure case: the AI service is unreachable during capture.
    The session must NOT stick in `analyzing`, no prediction is persisted,
    no routing fires, and the API surfaces a structured 503 (not a 500)."""
    from app.services import predict_service as predict_module
    from app.services.ai_client import AiWireError

    demo_session = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@ecolamp.campus", "password": "demo123"},
    ).json()["token"]
    before = user_points(demo_user_id())

    class _DownAi:
        def predict(self, db, user, image_bytes, image_url=None):
            raise AiWireError("AI service unreachable")

    import app.services.deposit_service as ds_module

    fake = _DownAi()
    monkeypatch.setattr(predict_module, "PredictService", lambda *a, **k: fake)
    monkeypatch.setattr(ds_module, "PredictService", lambda *a, **k: fake)

    session = create_capture_session(client, {"Authorization": f"Bearer {demo_session}"})
    r = client.post(
        "/api/v1/deposit/capture",
        data={"operation_id": session["operation_id"], "station_code": "ST-001"},
        files={"image": ("snap.jpg", b"frame", "image/jpeg")},
        headers={"X-Station-Key": STATION_KEY},
    )
    assert r.status_code == 503, r.text
    assert r.json().get("code") == "AI_UNAVAILABLE"
    with SessionLocal() as db:
        assert db.query(AiPrediction).count() == 0, "no prediction on AI outage"
        s = db.query(DepositSession).filter(
            DepositSession.operation_id == session["operation_id"]
        ).first()
        assert s.status == "capture", "session returns to capture for a retake"
    assert user_points(demo_user_id()) == before, "AI outage must never award points"


# --------------------------------------------------------------------------
# Capture -> physical event still required for points
# --------------------------------------------------------------------------

def test_capture_can_then_complete_via_physical_event(client, auth, monkeypatch):
    from .conftest import FakeAi, confirm_event

    install_fake_ai(monkeypatch, FakeAi("plastic", 0.95))
    user_id = demo_user_id()
    before = user_points(user_id)

    session = create_capture_session(client, auth)
    code, routed = capture(client, session["operation_id"])
    assert code == 200 and routed["status"] == "pending"

    # Physical MQTT event (HTTP callback parity path) still awards the points.
    r = client.post(
        "/api/v1/deposit/callback/event",
        headers={"X-Station-Key": STATION_KEY},
        json=confirm_event(
            session["operation_id"], position=1, weight=18.4, carriage=1,
        ),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
    assert r.json()["points_awarded"] == 5
    assert user_points(user_id) == before + 5


def test_routed_capture_never_awards_points_from_http(client, auth, monkeypatch):
    from .conftest import FakeAi

    install_fake_ai(monkeypatch, FakeAi("metal", 0.91))
    user_id = demo_user_id()
    before = user_points(user_id)
    session = create_capture_session(client, auth)
    code, routed = capture(client, session["operation_id"])
    assert code == 200 and routed["status"] == "pending"
    assert routed["potential_points"] == 10
    assert user_points(user_id) == before, "capture must never award points"


def test_callback_without_station_key_cannot_award_points(client, auth, monkeypatch):
    from .conftest import FakeAi, confirm_event

    install_fake_ai(monkeypatch, FakeAi("plastic", 0.95))
    user_id = demo_user_id()
    before = user_points(user_id)
    session = create_capture_session(client, auth)
    code, routed = capture(client, session["operation_id"])
    assert code == 200 and routed["status"] == "pending"

    # An unauthenticated caller fabricating a deposit_result must be rejected:
    # no station key, no header at all — the HTTP parity path is internet
    # reachable and shares the same secret as the capture endpoint.
    r = client.post(
        "/api/v1/deposit/callback/event",
        json=confirm_event(
            session["operation_id"], position=1, weight=18.4, carriage=1,
        ),
    )
    assert r.status_code == 401
    assert user_points(user_id) == before, "unauthenticated callback must not award points"
    with SessionLocal() as db:
        assert db.query(DepositSession).filter(
            DepositSession.operation_id == session["operation_id"]
        ).first().status == "pending"


def test_callback_wrong_station_key_rejected(client, auth, monkeypatch):
    from .conftest import FakeAi, confirm_event

    install_fake_ai(monkeypatch, FakeAi("plastic", 0.95))
    session = create_capture_session(client, auth)
    code, routed = capture(client, session["operation_id"])
    assert code == 200 and routed["status"] == "pending"
    r = client.post(
        "/api/v1/deposit/callback/event",
        headers={"X-Station-Key": "wrong-key"},
        json=confirm_event(session["operation_id"], position=1, weight=18.4, carriage=1),
    )
    assert r.status_code == 401


def test_capture_extra_img_upload_encode(client, auth, monkeypatch):
    from .conftest import FakeAi

    install_fake_ai(monkeypatch, FakeAi("plastic", 0.95))
    session = create_capture_session(client, auth)
    code, result = capture(client, session["operation_id"], image=b"\xff\xd8\xff\xe0real-jpeg")
    assert code == 200, result