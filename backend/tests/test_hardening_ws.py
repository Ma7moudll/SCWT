"""WebSocket ownership (T17): a valid token for user A must be closed with
4403 when subscribing to user B's operation; bad tokens get 4401."""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from .conftest import FakeAi, _predict
from .test_deposit import create_session


def _second_user_token(client) -> str:
    """Registers + logs in an attacker (non-owning) account."""
    from .conftest import register_and_login
    headers = register_and_login(client, "attacker@recycle.vision", "password123")
    return headers["Authorization"].split(" ", 1)[1]


def _first_message(client, url: str):
    """Returns the first WS frame; tolerates both starlette behaviours
    (returning the close dict OR raising WebSocketDisconnect)."""
    try:
        with client.websocket_connect(url) as ws:
            return ws.receive()
    except WebSocketDisconnect as exc:
        return {"type": "websocket.close", "code": exc.code}


def test_ws_rejects_other_users_operation(client, demo_session, publisher, monkeypatch):
    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, {"Authorization": f"Bearer {demo_session}"}, pred)
    operation_id = session["operation_id"]

    attacker_token = _second_user_token(client)
    message = _first_message(
        client, f"/ws/deposits/{operation_id}?token={attacker_token}"
    )
    assert message["type"] == "websocket.close"
    assert message["code"] == 4403


def test_ws_rejects_invalid_token(client):
    message = _first_message(client, "/ws/deposits/OP-x?token=garbage")
    assert message["type"] == "websocket.close"
    assert message["code"] == 4401


def test_ws_allows_owner_and_sends_subscribed(client, demo_session, publisher, monkeypatch):
    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, {"Authorization": f"Bearer {demo_session}"}, pred)
    operation_id = session["operation_id"]

    with client.websocket_connect(
        f"/ws/deposits/{operation_id}?token={demo_session}"
    ) as ws:
        message = ws.receive_json()
        assert message["type"] == "subscribed"
        assert message["operation_id"] == operation_id
        ws.close()
