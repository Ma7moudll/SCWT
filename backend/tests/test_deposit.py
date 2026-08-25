"""Deposit lifecycle tests: session creation, routing command, and the full
physical-event validation matrix. Points ONLY ever come from a valid MQTT
deposit_result event — never from session creation or any HTTP shortcut."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import DepositSession, LeaderboardEntry, User, WasteEvent

from .conftest import FakeAi, FakePublisher, _predict, confirm_event


def create_session(client, auth, prediction) -> dict:
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": prediction["prediction_id"], "station_id": "st-001"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def complete(client, operation_id: str, **kwargs) -> dict:
    r = client.post(
        "/api/v1/deposit/callback/event",
        headers={"X-Station-Key": "ecolamp-dev-station-key"},
        json=confirm_event(operation_id, **kwargs),
    )
    return r.status_code, r.json()


def user_points(user_id: str) -> int:
    with SessionLocal() as db:
        return db.get(User, user_id).points


def user_balance_delta(operation_id: str, predicted: int) -> int:
    """Points before the deposit (session is not awarded at creation)."""
    with SessionLocal() as db:
        user = db.query(User).join(DepositSession, DepositSession.user_id == User.id).filter(
            DepositSession.operation_id == operation_id
        ).first()
        total = db.query(WasteEvent).filter(WasteEvent.operation_id == operation_id).first()
        return predicted if (total and total.status == "confirmed") else 0


def _create_and_get_user_id(client, demo_session):
    with SessionLocal() as db:
        return db.query(User).filter(User.email == "demo@ecolamp.campus").first().id


# --------------------------------------------------------------------------
# Session creation
# --------------------------------------------------------------------------

def test_create_session_issues_route_command(client, auth, plastic_prediction, publisher):
    session = create_session(client, auth, plastic_prediction)
    assert session["status"] == "pending"
    assert session["expected_position"] == 1
    assert session["predicted_class"] == "plastic"
    assert session["potential_points"] == 5
    # Route command carries the routing position + mode, not the points.
    assert publisher.commands, "route command must be published"
    cmd = publisher.commands[-1]
    assert cmd["destination_position"] == 1
    assert cmd["mode"] == "automatic"  # confidence 0.95 = high


def test_session_creation_never_awards_points(client, auth, plastic_prediction, publisher):
    user_id = _create_and_get_user_id(client, auth)
    before = user_points(user_id)
    create_session(client, auth, plastic_prediction)
    assert user_points(user_id) == before, "session creation must not change points"


def test_low_confidence_prediction_cannot_route(client, auth, demo_session, monkeypatch):
    from app.routers import ai as ai_router
    from app.services.predict_service import PredictService

    monkeypatch.setattr(
        ai_router, "PredictService", lambda: PredictService(ai=FakeAi("plastic", 0.40))
    )
    pred = _predict(client, demo_session, FakeAi("plastic", 0.40), monkeypatch)
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": pred["prediction_id"], "station_id": "st-001"},
    )
    assert r.status_code == 422
    assert "confidence" in r.json()["error"].lower()


def test_expired_prediction_rejected(client, auth, plastic_prediction):
    op_id = plastic_prediction["prediction_id"]
    with SessionLocal() as db:
        from app.models import AiPrediction

        p = db.get(AiPrediction, op_id)
        p.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": op_id, "station_id": "st-001"},
    )
    assert r.status_code == 422


def test_session_for_other_users_prediction_rejected(client, auth, plastic_prediction):
    # Register a second user and try to use the first user's prediction.
    from .conftest import register_and_login
    headers2 = register_and_login(client, "second@uni.edu")
    r = client.post(
        "/api/v1/deposit/session",
        headers=headers2,
        json={"ai_prediction_id": plastic_prediction["prediction_id"], "station_id": "st-001"},
    )
    assert r.status_code == 422


def test_unknown_station_rejected(client, auth, plastic_prediction):
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": plastic_prediction["prediction_id"], "station_id": "st-999"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Completion via physical event (HTTP callback parity path)
# --------------------------------------------------------------------------

def test_valid_deposit_awards_points_once(client, auth, plastic_prediction):
    user_id = _create_and_get_user_id(client, auth)
    before = user_points(user_id)
    session = create_session(client, auth, plastic_prediction)

    code, result = complete(client, session["operation_id"],
                            position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    assert code == 200, result
    assert result["status"] == "confirmed"
    assert result["points_awarded"] == 5
    assert user_points(user_id) == before + 5

    # waste_event persisted
    with SessionLocal() as db:
        ev = db.query(WasteEvent).filter(WasteEvent.operation_id == session["operation_id"]).first()
        assert ev is not None
        assert ev.status == "confirmed"
        assert ev.points_awarded == 5
        # student + faculty leaderboard upserted
        student = db.query(LeaderboardEntry).filter(LeaderboardEntry.scope == "students").first()
        assert student.points == before + 5
        # deposit session closed
        s = db.query(DepositSession).filter(DepositSession.operation_id == session["operation_id"]).first()
        assert s.status == "confirmed"


def test_duplicate_event_rejected_409(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    complete(client, session["operation_id"], position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    code, result = complete(client, session["operation_id"], position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    assert code == 409
    assert "already" in result["error"]


def test_wrong_position_rejected(client, auth, plastic_prediction):
    user_id = _create_and_get_user_id(client, auth)
    before = user_points(user_id)
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"],
                            position=2, weight=18.4, stable=True, beam=True, mech=True, carriage=2)
    assert code == 200
    assert result["status"] == "rejected"
    assert "wrong_position" in result["reject_reason"]
    assert user_points(user_id) == before, "rejected deposit must not award points"


def test_underweight_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"],
                            position=1, weight=0.5, stable=True, beam=True, mech=True, carriage=1)
    assert result["status"] == "rejected"
    assert "underweight" in result["reject_reason"]


def test_unstable_weight_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"],
                            position=1, weight=18.4, stable=False, beam=True, mech=True, carriage=1)
    assert result["status"] == "rejected"
    assert "stable" in result["reject_reason"]


def test_no_beam_event_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"],
                            position=1, weight=18.4, stable=True, beam=False, mech=True, carriage=1)
    assert result["status"] == "rejected"
    assert "beam" in result["reject_reason"]


def test_no_mechanical_confirmation_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"],
                            position=1, weight=18.4, stable=True, beam=True, mech=False, carriage=1)
    assert result["status"] == "rejected"
    assert "mechanical" in result["reject_reason"]


def test_carriage_not_at_position_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"],
                            position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=3)
    assert result["status"] == "rejected"
    assert "carriage not at deposit position" in result["reject_reason"]


def test_machine_reported_failure_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"],
                            status="jam", position=1, weight=0.0, stable=False, beam=False, mech=False, carriage=1)
    assert result["status"] == "rejected"
    assert "jam" in result["reject_reason"]


def test_station_mismatch_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    code, result = complete(client, session["operation_id"], station="ST-ORPHAN",
                            position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    assert result["status"] == "rejected"
    assert "station" in result["reject_reason"]


def test_unknown_operation_rejected(client):
    code, result = complete(client, "OP-20990101-999999", position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    assert code == 404


def test_expired_session_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    with SessionLocal() as db:
        s = db.query(DepositSession).filter(DepositSession.operation_id == session["operation_id"]).first()
        s.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    code, result = complete(client, session["operation_id"],
                            position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    assert result["status"] == "expired"
    assert "expired" in result["reject_reason"]
    assert result["points_awarded"] == 0
    # expired sessions are auditable but never award points
    with SessionLocal() as db:
        ev = db.query(WasteEvent).filter(WasteEvent.operation_id == session["operation_id"]).first()
        assert ev is not None
        assert ev.points_awarded == 0


def test_metal_awards_10_points(client, auth, metal_prediction):
    user_id = _create_and_get_user_id(client, auth)
    before = user_points(user_id)
    session = create_session(client, auth, metal_prediction)
    code, result = complete(client, session["operation_id"],
                            position=2, weight=25.0, stable=True, beam=True, mech=True, carriage=2)
    assert result["status"] == "confirmed"
    assert result["points_awarded"] == 10
    assert user_points(user_id) == before + 10


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------

def test_cancel_pending_session(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    r = client.post(
        f"/api/v1/deposit/{session['operation_id']}/cancel", headers=auth
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_cancel_completed_deposit_rejected(client, auth, plastic_prediction):
    session = create_session(client, auth, plastic_prediction)
    complete(client, session["operation_id"], position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    r = client.post(
        f"/api/v1/deposit/{session['operation_id']}/cancel", headers=auth
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Live phase state machine (machine `state_changed` -> persisted status)
# --------------------------------------------------------------------------

def _apply(svc, operation_id: str, machine_state: str):
    from app.database import SessionLocal

    with SessionLocal() as db:
        return svc.apply_machine_state(
            db, {"operation_id": operation_id, "state": machine_state, "station_id": "ST-001"}
        )


def test_machine_state_progression_persisted(client, auth, plastic_prediction):
    from app.services.deposit_service import DepositService

    session = create_session(client, auth, plastic_prediction)
    op = session["operation_id"]
    svc = DepositService(publisher=FakePublisher())
    for machine, status in [
        ("ROUTING", "routing"),
        ("MOVING", "moving"),
        ("POSITIONED", "ready"),
        ("DETECTING", "detecting"),
        ("MEASURING", "measuring"),
    ]:
        out = _apply(svc, op, machine)
        assert out is not None and out["status"] == status, f"{machine} -> {status}"

    # READY_FOR_DEPOSIT is a synonym for the already-reached 'ready' phase,
    # so it is a monotonic no-op rather than a regression.
    assert _apply(svc, op, "READY_FOR_DEPOSIT") is None

    # monotonic: a late telemetry frame cannot regress the phase
    assert _apply(svc, op, "ROUTING") is None


def test_machine_state_never_awards_points(client, auth, plastic_prediction):
    from app.services.deposit_service import DepositService

    session = create_session(client, auth, plastic_prediction)
    user_id = _create_and_get_user_id(client, auth)
    before = user_points(user_id)
    svc = DepositService(publisher=FakePublisher())
    for state in ("ROUTING", "MOVING", "READY_FOR_DEPOSIT", "DETECTING", "MEASURING"):
        _apply(svc, session["operation_id"], state)
    assert user_points(user_id) == before, "live phase updates must never award points"


def test_terminal_blocks_further_state_transitions(client, auth, plastic_prediction):
    from app.database import SessionLocal
    from app.models import DepositSession
    from app.services.deposit_service import DepositService

    session = create_session(client, auth, plastic_prediction)
    op = session["operation_id"]
    svc = DepositService(publisher=FakePublisher())
    _apply(svc, op, "MOVING")

    # terminal confirmed
    code, result = complete(client, op, position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    assert result["status"] == "confirmed"
    assert _apply(svc, op, "MEASURING") is None
    with SessionLocal() as db:
        s = db.query(DepositSession).filter(DepositSession.operation_id == op).first()
        assert s.status == "confirmed"


def test_cancel_during_live_phase(client, auth, plastic_prediction):
    from app.services.deposit_service import DepositService

    session = create_session(client, auth, plastic_prediction)
    svc = DepositService(publisher=FakePublisher())
    _apply(svc, session["operation_id"], "ROUTING")
    _apply(svc, session["operation_id"], "MOVING")
    r = client.post(f"/api/v1/deposit/{session['operation_id']}/cancel", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_duplicate_terminal_never_double_awards(client, auth, plastic_prediction):
    user_id = _create_and_get_user_id(client, auth)
    before = user_points(user_id)
    session = create_session(client, auth, plastic_prediction)
    op = session["operation_id"]
    for _ in range(2):
        code, _ = complete(client, op, position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
        assert code in (200, 409)
    assert user_points(user_id) == before + 5, "duplicate terminal event must not double-award"
    with SessionLocal() as db:
        rows = db.query(WasteEvent).filter(WasteEvent.operation_id == op).all()
        confirmed = [r for r in rows if r.status == "confirmed"]
        assert len(confirmed) == 1
        assert sum(r.points_awarded for r in rows) == 5