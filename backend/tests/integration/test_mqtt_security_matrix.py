"""MQTT security matrix: adversarial traffic against a REAL authenticated
broker proves the backend never trusts the wire.

Covers the anti-cheat matrix from the hardening plan:

    malformed payloads      -> ignored, no crash, no points
    forged success event    -> rejected by physics gates (wrong position)
    forged station claim    -> rejected by station match
    unknown operation id    -> silently ignored
    replay after terminal   -> duplicate detected, points awarded exactly once
    state after terminal    -> terminal blocks further transitions
    wrong broker password   -> connection refused by mosquitto
    cross-station publish   -> denied by the broker ACL

The broker fixture lives in tests/integration/conftest.py.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest

from conftest import BROKER_PASS, BROKER_HOST, BROKER_PORT, BROKER_USER, \
    STATION_PASS, STATION_USER, mosquitto_pub

PREFIX = "scwt/stations"
EVENT_TOPIC = f"{PREFIX}/st-001/event"
STATE_TOPIC = f"{PREFIX}/st-001/state"


@pytest.fixture
def gateway_connected(broker):
    from app.state import get_gateway

    gw = get_gateway()
    assert gw is not None
    assert gw.wait_connected(15), "backend MQTT gateway did not connect to broker"
    return gw


@pytest.fixture
def pending_session(client, auth, monkeypatch):
    """A real pending deposit session for st-001 (plastic -> position 1)."""
    from app.routers import ai as ai_router
    from app.services.predict_service import PredictService
    from tests.conftest import FakeAi

    monkeypatch.setattr(
        ai_router, "PredictService", lambda: PredictService(ai=FakeAi("plastic", 0.95))
    )
    pred = client.post(
        "/api/v1/ai/predict",
        headers=auth,
        files={"image": ("capture.jpg", b"fake-jpeg-bytes", "image/jpeg")},
    )
    assert pred.status_code == 200, pred.text
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": pred.json()["prediction_id"], "station_id": "st-001"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _points(client, auth) -> int:
    return client.get("/api/v1/users/me", headers=auth).json()["user"]["points"]


def _status(client, auth, operation_id) -> dict:
    return client.get(f"/api/v1/deposit/{operation_id}", headers=auth).json()


def _wait_terminal(client, auth, operation_id, want: str, timeout=15.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        cur = _status(client, auth, operation_id)
        if cur["status"] == want:
            return cur
        time.sleep(0.2)
    return None


def _valid_success_payload(operation_id: str) -> str:
    """A physics-CONSISTENT terminal event (what an honest machine would send)."""
    return json.dumps({
        "operation_id": operation_id,
        "event": "deposit_result",
        "status": "confirmed",
        "actual_position": 1,
        "carriage_position": 1,
        "weight_grams": 50.0,
        "weight_stable": True,
        "beam_event_seen": True,
        "mechanical_confirmed": True,
        "station_id": "st-001",
    })


# -- transport-level security -------------------------------------------------

def test_broker_rejects_wrong_password(broker):
    rc = mosquitto_pub(
        f"{PREFIX}/st-001/heartbeat", "{}", STATION_USER, "totally-wrong-password"
    )
    assert rc != 0, "mosquitto accepted a wrong password"


def test_broker_rejects_anonymous(broker):
    try:
        proc_rc = subprocess_rc_anonymous()
    except FileNotFoundError:
        pytest.skip("mosquitto_pub not installed")
    assert proc_rc != 0, "mosquitto accepted an anonymous publish"


def subprocess_rc_anonymous() -> int:
    import subprocess

    return subprocess.run(
        [
            "/opt/homebrew/bin/mosquitto_pub",
            "-h", BROKER_HOST, "-p", str(BROKER_PORT),
            "-q", "1",
            "-t", f"{PREFIX}/st-001/event",
            "-m", '{"operation_id":"anon","event":"deposit_result","status":"confirmed"}',
        ],
        capture_output=True, timeout=10,
    ).returncode


def test_broker_acl_denies_cross_station_publish(broker):
    """ST-001 credentials must NOT be able to write ST-002's event topic.

    mosquitto denies the PUBLISH but still PUBACKs (rc 0x87), so the client
    exit code is 0 either way. The security property we actually care about is
    that the denied message NEVER REACHES the other station's topic — so a
    backend-identity subscriber on st-002/event must receive nothing.
    """
    import subprocess

    sub = subprocess.Popen(
        [
            "/opt/homebrew/bin/mosquitto_sub",
            "-h", BROKER_HOST, "-p", str(BROKER_PORT),
            "-u", BROKER_USER, "-P", BROKER_PASS,
            "-t", f"{PREFIX}/st-002/event",
            "-W", "3",  # exit after 3s idle
        ],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    time.sleep(0.8)  # let the subscription register
    rc = mosquitto_pub(
        f"{PREFIX}/st-002/event", _valid_success_payload("acl-probe"), STATION_USER, STATION_PASS
    )
    assert rc == 0, "broker refused a valid connection outright"
    received = sub.communicate(timeout=15)[0].strip()

    assert not received, (
        f"cross-station publish PROPAGATED to st-002: {received[:120]!r}"
    )


def test_broker_acl_allows_own_station_publish(broker):
    rc = mosquitto_pub(f"{PREFIX}/st-001/heartbeat", '{"ok":true}', STATION_USER, STATION_PASS)
    assert rc == 0, "broker denied a legitimate same-station publish"


# -- payload-level attacks -----------------------------------------------------

def test_malformed_payloads_neither_crash_nor_award(client, auth, pending_session,
                                                    gateway_connected):
    op = pending_session["operation_id"]
    before = _points(client, auth)

    garbage = [
        b"not-json-at-all",                      # non-JSON
        b'["a","json","array"]',                 # JSON but not an object
        b'{"no_operation_id": true}',            # object without operation id
        b"\xff\xfebinary-junk",                  # undecodable bytes
    ]
    for payload in garbage:
        rc = mosquitto_pub(EVENT_TOPIC, payload.decode("utf-8", "ignore"), BROKER_USER, BROKER_PASS)
        assert rc == 0, f"broker refused backend identity publish ({payload[:20]!r})"

    time.sleep(1.0)  # give the handler every chance to misbehave

    cur = _status(client, auth, op)
    assert cur["status"] == "pending", f"malformed payloads moved the deposit: {cur['status']}"
    assert _points(client, auth) == before, "malformed payloads changed points"


def test_forged_wrong_position_event_rejected(client, auth, pending_session, gateway_connected):
    """A compromised station fabricates a 'successful' deposit at the WRONG
    compartment. The backend must reject it on physics gates."""
    op = pending_session["operation_id"]
    forged = json.loads(_valid_success_payload(op))
    forged["actual_position"] = 3       # routed to 1
    forged["carriage_position"] = 3
    rc = mosquitto_pub(EVENT_TOPIC, json.dumps(forged), BROKER_USER, BROKER_PASS)
    assert rc == 0

    rejected = _wait_terminal(client, auth, op, "rejected")
    assert rejected is not None, "forged wrong-position event was never rejected"
    assert "wrong_position" in rejected["reject_reason"]
    assert rejected["points_awarded"] == 0


def test_forged_station_mismatch_event_rejected(client, auth, pending_session, gateway_connected):
    """Event published on ST-001's topic but claiming to belong to ST-999."""
    op = pending_session["operation_id"]
    forged = json.loads(_valid_success_payload(op))
    forged["station_id"] = "st-999"
    rc = mosquitto_pub(EVENT_TOPIC, json.dumps(forged), BROKER_USER, BROKER_PASS)
    assert rc == 0

    rejected = _wait_terminal(client, auth, op, "rejected")
    assert rejected is not None, "forged station-mismatch event was never rejected"
    assert "station" in (rejected["reject_reason"] or "").lower()
    assert rejected["points_awarded"] == 0


def test_unknown_operation_event_ignored(client, auth, gateway_connected):
    ghost_op = str(uuid.uuid4())
    before = _points(client, auth)
    rc = mosquitto_pub(EVENT_TOPIC, _valid_success_payload(ghost_op), BROKER_USER, BROKER_PASS)
    assert rc == 0

    time.sleep(1.0)
    r = client.get(f"/api/v1/deposit/{ghost_op}", headers=auth)
    assert r.status_code in (404, 422), (
        "unknown operation materialised out of thin air"
    )
    assert _points(client, auth) == before, "unknown operation awarded points"


# -- ordering / replay ---------------------------------------------------------

def test_valid_event_confirms_once_and_replay_is_ignored(client, auth, pending_session,
                                                         gateway_connected):
    """Honest-looking valid event -> confirmed +5 exactly once; an exact replay
    of the same MQTT message must never double-award."""
    op = pending_session["operation_id"]
    start = _points(client, auth)
    payload = _valid_success_payload(op)

    rc = mosquitto_pub(EVENT_TOPIC, payload, BROKER_USER, BROKER_PASS)
    assert rc == 0
    confirmed = _wait_terminal(client, auth, op, "confirmed")
    assert confirmed is not None, "valid event was never confirmed"
    assert confirmed["points_awarded"] == 5
    assert _points(client, auth) == start + 5

    # Replay the byte-identical message.
    rc = mosquitto_pub(EVENT_TOPIC, payload, BROKER_USER, BROKER_PASS)
    assert rc == 0
    time.sleep(1.5)

    still = _status(client, auth, op)
    assert still["status"] == "confirmed", "replay mutated a terminal deposit"
    assert still["points_awarded"] == 5, "replay double-awarded points"
    assert _points(client, auth) == start + 5, "replay double-awarded points"


def test_state_after_terminal_is_blocked(client, auth, pending_session, gateway_connected):
    """A late machine-state frame arriving AFTER the deposit went terminal must
    not resurrect or mutate it."""
    op = pending_session["operation_id"]
    rc = mosquitto_pub(EVENT_TOPIC, _valid_success_payload(op), BROKER_USER, BROKER_PASS)
    assert rc == 0
    confirmed = _wait_terminal(client, auth, op, "confirmed")
    assert confirmed is not None

    late_state = json.dumps({
        "operation_id": op,
        "state": "MOVING",
        "position": 2,
        "station_id": "st-001",
    })
    rc = mosquitto_pub(STATE_TOPIC, late_state, BROKER_USER, BROKER_PASS)
    assert rc == 0
    time.sleep(1.5)

    still = _status(client, auth, op)
    assert still["status"] == "confirmed", "late state mutated a terminal deposit"
    assert still["actual_position"] == 1, "late state rewrote actual position"
