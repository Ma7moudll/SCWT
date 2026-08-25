"""WebSocket deposit-state tests.

The socket is a transport for authoritative deposit states (PostgreSQL-backed),
never a source of truth and never a point-awarding path. These tests verify
the auth gate, the subscribed handshake and that state + terminal deposits are
delivered for the operation the client subscribed to.
"""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from app.database import SessionLocal
from app.services.deposit_service import DepositService
from app.services.event_bus import event_bus

from .conftest import FakePublisher, _predict, confirm_event


def _subscribe(client, token: str, operation_id: str):
    return client.websocket_connect(f"/ws/deposits/{operation_id}?token={token}")


def test_ws_requires_valid_token(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/deposits/OP-TEST-1") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_subscribes_and_delivers_state_and_terminal(client, demo_session, plastic_prediction, publisher):
    from .test_deposit import create_session

    session = create_session(client, {"Authorization": f"Bearer {demo_session}"}, plastic_prediction)
    op = session["operation_id"]

    with _subscribe(client, demo_session, op) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "subscribed"
        assert msg["operation_id"] == op

        # A machine state transition (as the MQTT handler would apply it and
        # then forward the authoritative deposit to the bus).
        with SessionLocal() as db:
            state = DepositService(publisher=FakePublisher()).apply_machine_state(
                db, {"operation_id": op, "state": "MOVING", "station_id": "ST-001"}
            )
            event_bus.publish(op, {"type": "state", "deposit": state})
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["deposit"]["status"] == "moving"
        assert msg["deposit"]["points_awarded"] == 0

        # A terminal deposit_result (as the MQTT handler would publish it).
        with SessionLocal() as db:
            result = DepositService(publisher=FakePublisher()).complete_from_event(
                db, confirm_event(op, position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
            )
            event_bus.publish(op, {"type": "terminal", "deposit": result})
        msg = ws.receive_json()
        assert msg["type"] == "terminal"
        assert msg["deposit"]["status"] == "confirmed"
        assert msg["deposit"]["points_awarded"] == 5


def test_ws_does_not_deliver_other_operations(client, demo_session, plastic_prediction, publisher, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.services.predict_service import PredictService
    from app.routers import ai as ai_router
    from .conftest import FakeAi
    from .test_deposit import create_session

    auth = {"Authorization": f"Bearer {demo_session}"}
    session_a = create_session(client, auth, plastic_prediction)
    op_a = session_a["operation_id"]

    monkeypatch.setattr(ai_router, "PredictService", lambda: PredictService(ai=FakeAi("metal", 0.91)))
    pred_b = _predict(client, demo_session, FakeAi("metal", 0.91), monkeypatch)
    session_b = create_session(client, auth, pred_b)
    op_b = session_b["operation_id"]

    with _subscribe(client, demo_session, op_a) as ws_a:
        assert ws_a.receive_json()["type"] == "subscribed"

        # Publish a terminal for the OTHER operation; this subscriber must not
        # receive it.
        with SessionLocal() as db:
            result = DepositService(publisher=FakePublisher()).complete_from_event(
                db, confirm_event(op_b, position=2, weight=25.0, stable=True, beam=True, mech=True, carriage=2)
            )
            event_bus.publish(op_b, {"type": "terminal", "deposit": result})

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(ws_a.receive_json)
            try:
                fut.result(timeout=1.0)
                received = True
            except Exception:
                received = False
        assert not received, "subscriber must not receive events for other operations"
