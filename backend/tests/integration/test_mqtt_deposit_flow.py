"""Full-chain integration test:

    FastAPI (backend) ──route command──▶ MQTT broker ◀─subscribe── SCWTSimulator
    backend ◀─────────────── deposit_result sensor events ────────── simulator

The simulator behaves like the future ESP32 firmware: it subscribes to its
station command topic and executes a real deposit plan on MQTT. The backend
validates the physics event and awards points inside one transaction.

Requires a local mosquitto broker (skipped when unavailable) and the
`mosquitto` binary from Homebrew.
"""
from __future__ import annotations

import time

import pytest

# The authenticated broker fixture lives in tests/integration/conftest.py.
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1896  # must match backend/tests/conftest.py env
BROKER_USER = "backend"
BROKER_PASS = "itest-broker-pass"  # must match backend/tests/conftest.py env


@pytest.fixture
def simulator(broker):
    """A real simulator connected to the real broker, listening for commands."""
    import sys

    from pathlib import Path

    sim_dir = Path(__file__).resolve().parents[3] / "hardware-simulator"
    sys.path.insert(0, str(sim_dir))

    from config import SimConfig
    from hardware import Carriage, LoadCell
    from simulator import SCWTSimulator

    cfg = SimConfig()
    cfg.broker_host = BROKER_HOST
    cfg.broker_port = BROKER_PORT
    cfg.mqtt_username = BROKER_USER
    cfg.mqtt_password = BROKER_PASS
    cfg.movement_time_seconds = 0.0

    sim = SCWTSimulator(
        config=cfg,
        carriage=Carriage(initial_position=1, movement_time_per_step=0.0),
        load_cell=LoadCell(noise_grams=0, seed=7),
    )
    sim.mqtt.set_command_handler(sim._on_command)
    sim.mqtt.start(cfg.command_topic())
    assert sim.mqtt.connected.wait(10), "simulator did not connect to broker"
    time.sleep(0.5)  # subscription ack before the backend publishes
    yield sim
    sim.mqtt.stop()


@pytest.fixture
def gateway_connected():
    from app.state import get_gateway

    gw = get_gateway()
    assert gw is not None
    assert gw.wait_connected(15), "backend MQTT gateway did not connect to broker"
    return gw


def _wait_for_confirmed(client, auth, operation_id, timeout=20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/deposit/{operation_id}", headers=auth)
        if r.status_code == 200:
            session = r.json()
            if session["status"] == "confirmed":
                return session
        time.sleep(0.2)
    raise AssertionError(f"deposit {operation_id} never reached 'confirmed'")


def test_full_chain_mqtt_deposit_awards_points(client, auth, demo_session,
                                               simulator, gateway_connected, monkeypatch):
    from app.routers import ai as ai_router
    from app.services.predict_service import PredictService
    from tests.conftest import FakeAi

    monkeypatch.setattr(
        ai_router, "PredictService", lambda: PredictService(ai=FakeAi("plastic", 0.95))
    )

    # 1. Predict on the backend (routing policy resolves to position 1, +5).
    pred = client.post(
        "/api/v1/ai/predict",
        headers=auth,
        files={"image": ("capture.jpg", b"fake-jpeg-bytes", "image/jpeg")},
    )
    assert pred.status_code == 200, pred.text
    prediction = pred.json()

    # 2. Create the session -> backend publishes the MQTT route command.
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": prediction["prediction_id"], "station_id": "st-001"},
    )
    assert r.status_code == 200, r.text
    session = r.json()
    operation_id = session["operation_id"]

    # 3. The simulator executes the deposit over MQTT; the backend validates it.
    confirmed = _wait_for_confirmed(client, auth, operation_id)
    assert confirmed["status"] == "confirmed"
    assert confirmed["actual_position"] == 1
    assert confirmed["points_awarded"] == 5
    assert confirmed["weight_g"] > 0

    # 4. Points landed exactly once (backend validates, never the client).
    me = client.get("/api/v1/users/me", headers=auth).json()["user"]
    assert me["points"] == 45 + 5

    # 5. The audit trail row exists.
    history = client.get("/api/v1/waste/history", headers=auth).json()["items"]
    ev = [e for e in history if e["operation_id"] == operation_id][0]
    assert ev["points_awarded"] == 5

    # 6. The station registry observed the simulator's telemetry.
    stations = client.get("/api/v1/stations", headers=auth).json()["items"]
    st = [s for s in stations if s.get("station_code") == "ST-001"]
    assert st, "station should be present in the registry"
    assert st[0]["status"] == "online"
    assert st[0]["state"] == "IDLE"


def test_full_chain_rejects_wrong_position(client, auth, demo_session,
                                           simulator, gateway_connected, monkeypatch):
    """The simulator lands the carriage at compartment 2; the backend (which
    routed to 1) must reject the deposit with a wrong-position reason."""
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
    ).json()

    # Override the simulator scenario so it ignores the route command and
    # physically settles at compartment 2 (a misrouted deposit).
    from scenarios import DepositPlan

    def misroute(command):
        plan = DepositPlan(name="wrong-position", destination_position=2, actual_position=2)
        simulator.run_plan(command["operation_id"], command["destination_position"], plan)

    simulator.mqtt.set_command_handler(misroute)

    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": pred["prediction_id"], "station_id": "st-001"},
    )
    session = r.json()
    operation_id = session["operation_id"]

    deadline = time.time() + 20
    status = None
    while time.time() < deadline:
        cur = client.get(f"/api/v1/deposit/{operation_id}", headers=auth).json()
        if cur["status"] == "rejected":
            status = cur
            break
        time.sleep(0.2)

    assert status, "deposit was never rejected"
    assert "wrong_position" in status["reject_reason"]
    assert status["points_awarded"] == 0

    # Rejections still leave an auditable trail row (0 points).
    history = client.get("/api/v1/waste/history", headers=auth).json()["items"]
    ev = [e for e in history if e["operation_id"] == operation_id]
    assert ev and ev[0]["points_awarded"] == 0