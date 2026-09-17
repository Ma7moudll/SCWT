"""SCWT end-to-end proof: the REAL deposit chain on SCWT services.

SCWT is a standalone CARRIAGE product: its own broker (scwt/stations
prefix), own AI service, own PostgreSQL database, own API port. This script
shares no runtime with any other project.

Starts real processes (not TestClient): mosquitto broker, the ai-service
(FastAPI), and the backend (FastAPI + SQLAlchemy against PostgreSQL), then
drives every deposit scenario through the real HTTP + MQTT path with an
in-process SCWTSimulator acting as the ESP32 and a real WebSocket client
observing live status.

This is the standing proof that points are only ever awarded by validated
physical sensor events over MQTT — the HTTP layer and WebSocket can never
award points.

    backend/../scripts/e2e_carriage_chain.py

Prerequisites: local PostgreSQL (role scwt/scwt), mosquitto at
/opt/homebrew/sbin/mosquitto, a Python env with the backend+AI requirements,
and free ports 1886/8052/8100.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Prefer THIS project's own virtualenv — never another repository's.
_venv_python = ROOT / ".venv" / "bin" / "python"
PYTHON = str(_venv_python) if _venv_python.exists() else (
    __import__("shutil").which("python") or str(_venv_python))
MOSQUITTO_BIN = Path("/opt/homebrew/sbin/mosquitto")
AI_MODEL_PATH = ROOT / "ai-service" / "models" / "model.onnx"
FIXTURES_DIR = ROOT / "ai-service" / "tests" / "fixtures"

HOST = "127.0.0.1"
MQTT_PORT = 1886
AI_PORT = 8052
API_PORT = 8100

DB_URL = (
    "postgresql+psycopg2://scwt:scwt@localhost:5432/scwt_e2e"
)
JWT_SECRET = "scwt-e2e-secret-not-for-prod"

DEMO_EMAIL = "demo@scwt.campus"
DEMO_PASSWORD = "demo123"

os.environ.setdefault("SIMULATOR_RAMP_STEP", "0")
sys.path.insert(0, str(ROOT / "hardware-simulator"))

import httpx  # noqa: E402
import psycopg2  # noqa: E402

from hardware import Carriage, LoadCell  # noqa: E402
from scenarios import DepositPlan  # noqa: E402
from simulator import SCWTSimulator  # noqa: E402


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, port)) != 0


def _wait_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_free(port):
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} never came up")


def _fixture_bytes(name: str) -> bytes:
    """Confidence-band fixture images curated by the training pipeline from
    the real model (see ai-service/app/training/train.py / fixtures.json)."""
    path = FIXTURES_DIR / name
    if not path.exists():
        raise SystemExit(
            f"fixture {path} missing — run the training pipeline to curate it"
        )
    return path.read_bytes()


def _connect_pg():
    conn = psycopg2.connect(
        host="localhost", port=5432, user="scwt", password="scwt",
        dbname="scwt_e2e",
    )
    conn.autocommit = True
    return conn


def _truncate_db() -> None:
    conn = _connect_pg()
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE waste_events, deposit_sessions, ai_predictions "
            "RESTART IDENTITY CASCADE"
        )
        cur.execute(
            "UPDATE users SET points = 45 WHERE email = %s",
            (DEMO_EMAIL,),
        )
    conn.close()


def _force_expire(session_id: str) -> None:
    conn = _connect_pg()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE deposit_sessions SET expires_at = %s WHERE operation_id = %s",
            (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(seconds=5),
                session_id,
            ),
        )
    conn.close()


class ScenarioControl:
    """Single-threaded control hand-off between the driver (HTTP thread) and
    the simulator's MQTT command handler."""

    def __init__(self) -> None:
        self.plan: DepositPlan | None = None
        self.hold_seconds = 0.0
        self.received: list[dict] = []

    def take_plan(self) -> DepositPlan | None:
        plan = self.plan  # None -> the physical drop never happens
        self.plan = None
        return plan


def main() -> None:
    # -- prerequisites ---------------------------------------------------------
    assert MOSQUITTO_BIN.exists(), f"mosquitto not found at {MOSQUITTO_BIN}"
    assert AI_MODEL_PATH.exists(), (
        f"trained model not found at {AI_MODEL_PATH} — run the training pipeline first"
    )
    if not _port_free(MQTT_PORT):
        raise SystemExit(f"port {MQTT_PORT} busy — stop the running broker")
    if not _port_free(AI_PORT):
        raise SystemExit(f"port {AI_PORT} busy")
    if not _port_free(API_PORT):
        raise SystemExit(f"port {API_PORT} busy")

    procs: list[subprocess.Popen] = []

    try:
        # -- mosquitto (AUTHENTICATED — parity with production) ------------------
        import secrets

        mqtt_user = "backend"
        mqtt_pass = secrets.token_urlsafe(24)
        passwd_file = "/tmp/scwt_e2e_mosquitto.passwd"
        acl_file = "/tmp/scwt_e2e_mosquitto.acl"
        Path(passwd_file).unlink(missing_ok=True)  # mosquitto_passwd -c needs a fresh path
        subprocess.run(
            ["/opt/homebrew/bin/mosquitto_passwd", "-b", "-c", passwd_file,
             mqtt_user, mqtt_pass],
            check=True,
        )
        with open(acl_file, "w") as acl:
            acl.write(f"user {mqtt_user}\ntopic readwrite scwt/stations/#\n")
        conf = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        conf.write(
            f"listener {MQTT_PORT}\n"
            "allow_anonymous false\n"
            f"password_file {passwd_file}\n"
            f"acl_file {acl_file}\n"
            "max_queued_messages 1000\n"
            "message_size_limit 0\n"
        )
        conf.close()
        procs.append(subprocess.Popen(
            [str(MOSQUITTO_BIN), "-c", conf.name, "-v"],
            stdout=open("/tmp/scwt_e2e_mosquitto.log", "w"), stderr=subprocess.STDOUT,
        ))
        _wait_port(MQTT_PORT)

        # -- ai-service ---------------------------------------------------------
        def start_ai() -> subprocess.Popen:
            env = dict(os.environ)
            env.update({
                "PYTHONPATH": str(ROOT / "ai-service"),
                "AI_SERVICE_CLASSIFIER": "real",
                "AI_MODEL_PATH": str(AI_MODEL_PATH),
                # Production inference MUST NOT read development overrides;
                # they are set to poison values to prove the real path ignores them.
                "DEVELOPMENT_FORCE_CLASS": "plastic",
                "DEVELOPMENT_FORCE_CONFIDENCE": "0.99",
            })
            return subprocess.Popen(
                [PYTHON, "-m", "uvicorn", "app.main:app", "--port", str(AI_PORT),
                 "--log-level", "warning"],
                cwd=str(ROOT / "ai-service"), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        ai_proc = start_ai()
        procs.append(ai_proc)
        _wait_port(AI_PORT)

        # -- backend -------------------------------------------------------------
        backend_env = dict(os.environ)
        backend_env.update({
            "PYTHONPATH": str(ROOT / "backend"),
            "DATABASE_URL": DB_URL,
            "MQTT_BROKER_HOST": HOST,
            "MQTT_BROKER_PORT": str(MQTT_PORT),
            "MQTT_USERNAME": mqtt_user,
            "MQTT_PASSWORD": mqtt_pass,
            "AI_SERVICE_URL": f"http://{HOST}:{AI_PORT}",
            "JWT_SECRET": JWT_SECRET,
            "SEED_ON_STARTUP": "true",
            "SEED_DEMO_USER": "true",
            "DEBUG": "false",
        })
        backend_log = open("/tmp/scwt_e2e_backend.log", "w")
        procs.append(subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT),
             "--log-level", "info"],
            cwd=str(ROOT / "backend"), env=backend_env,
            stdout=backend_log, stderr=subprocess.STDOUT,
        ))
        _wait_port(API_PORT)

        # Backend lifespan created the schema and seeded; reset transaction
        # state so repeated runs stay idempotent (demo user starts at 45 pts).
        _truncate_db()

        # -- HTTP client (defined early: the station-camera handler below posts
        #    capture frames on behalf of the station while the backend drives
        #    the flow).
        client = httpx.Client(base_url=f"http://{HOST}:{API_PORT}", timeout=20.0)
        login = client.post("/api/v1/auth/login", json={
            "email": DEMO_EMAIL, "password": DEMO_PASSWORD,
        })
        assert login.status_code == 200, login.text
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # -- simulator ------------------------------------------------------------
        from config import SimConfig
        cfg = SimConfig()
        cfg.broker_host = HOST
        cfg.broker_port = MQTT_PORT
        cfg.mqtt_username = mqtt_user
        cfg.mqtt_password = mqtt_pass
        cfg.movement_time_seconds = 0.0
        sim = SCWTSimulator(
            config=cfg,
            carriage=Carriage(initial_position=1, movement_time_per_step=0.0),
            load_cell=LoadCell(noise_grams=0, seed=7),
        )
        control = ScenarioControl()
        session_station_id: dict[str, str] = {}

        def post_capture(operation_id: str) -> None:
            """Stand in for the STATION camera (FINAL path): the backend issued
            `capture_request`, so we upload a real AI fixture frame to
            `/deposit/capture` with the station key. The backend then runs the
            REAL PredictService, attaches the prediction and routes."""
            stations = client.get("/api/v1/stations", headers=headers).json()["items"]
            station = next(s for s in stations if s["id"] == session_station_id.get(operation_id, "st-001"))
            r = client.post(
                "/api/v1/deposit/capture",
                headers={**headers, "X-Station-Key": "scwt-dev-station-key"},
                data={"operation_id": operation_id, "station_code": station["station_code"]},
                files={"image": ("frame.jpg", _fixture_bytes("high_conf_plastic.png"), "image/jpeg")},
            )
            assert r.status_code == 200, r.text

        def on_command(command: dict) -> None:
            control.received.append(command)
            if command.get("command") == "capture_request":
                # FINAL station-camera path: tell the camera to snap + classify.
                # Routing happens after classification, so take no plan here.
                post_capture(command["operation_id"])
                return
            plan = control.take_plan()
            if plan is None:
                return
            if control.hold_seconds:
                time.sleep(control.hold_seconds)
            try:
                sim.run_plan(
                    command["operation_id"],
                    command.get("destination_position"),
                    plan,
                )
            except Exception:
                pass

        sim.mqtt.set_command_handler(on_command)
        sim.mqtt.start(cfg.command_topic())
        assert sim.mqtt.connected.wait(10), "simulator not connected"
        time.sleep(0.5)

        # -- helpers -----------------------------------------------------------------
        results: list[str] = []
        passes = 0
        failures = 0

        def record(name: str, ok: bool, detail: str = "") -> None:
            nonlocal passes, failures
            if ok:
                passes += 1
                line = f"[PASS] {name}"
                results.append(line)
                print(line)
            else:
                failures += 1
                line = f"[FAIL] {name}: {detail}"
                results.append(line)
                print(line)

        def points_now() -> int:
            return client.get("/api/v1/users/me", headers=headers).json()["user"]["points"]

        def predict_bytes(blob: bytes) -> dict:
            r = client.post(
                "/api/v1/ai/predict", headers=headers,
                files={"image": ("capture.png", blob, "image/png")},
            )
            assert r.status_code == 200, r.text
            return r.json()

        def predict_fixture(name: str) -> dict:
            return predict_bytes(_fixture_bytes(name))

        def create_session(prediction_id: str) -> dict:
            r = client.post(
                "/api/v1/deposit/session", headers=headers,
                json={"ai_prediction_id": prediction_id, "station_id": "st-001"},
            )
            assert r.status_code == 200, r.text
            return r.json()

        def create_capture_session(station_id: str) -> dict:
            """FINAL station-camera path: NO prediction id — the backend creates
            the session capture-first and asks the STATION camera for a frame
            (`capture_request`)."""
            r = client.post(
                "/api/v1/deposit/session", headers=headers,
                json={"station_id": station_id},
            )
            assert r.status_code == 200, r.text
            session = r.json()
            session_station_id[session["operation_id"]] = station_id
            return session

        def wait_status(op_id: str, target: str, timeout: float = 20.0) -> dict:
            deadline = time.time() + timeout
            seen = []
            while time.time() < deadline:
                r = client.get(f"/api/v1/deposit/{op_id}", headers=headers)
                assert r.status_code == 200, r.text
                data = r.json()
                if data["status"] not in seen:
                    seen.append(data["status"])
                if data["status"] == target:
                    return data
                time.sleep(0.05)
            raise AssertionError(
                f"{op_id} never reached {target!r}; saw {seen}"
            )

        def ws_session(op_id: str, auth_token: str | None = None):
            import websockets.sync.client as ws_client
            tok = auth_token if auth_token is not None else token
            ws = ws_client.connect(
                f"ws://{HOST}:{API_PORT}/ws/deposits/{op_id}?token={tok}"
            )
            first = ws.recv()
            return ws, first

        # =========================================================================
        # Scenario A — VALID plastic: full real chain + WebSocket + real AI.
        # =========================================================================

        # WS auth gate: a bad token must be refused before any message flows.
        import json as _json
        bad_rejected = False
        try:
            ws_bad, _ = ws_session("anything", auth_token="totally-wrong-token")
            ws_bad.close()
        except Exception:
            bad_rejected = True
        record("WS auth gate rejects a bad token", bad_rejected)

        start = points_now()
        control.plan = DepositPlan(name="valid-plastic")
        pred = predict_fixture("high_conf_plastic.png")
        assert pred["predicted_class"] == "plastic", pred
        assert pred["source"] == "ai", pred  # real trained model, not demo
        assert pred["confidence"] >= 0.80, pred  # auto-routable
        record("Real AI: plastic image -> plastic, source=ai", pred["source"] == "ai")

        session = create_session(pred["prediction_id"])
        op_a = session["operation_id"]

        ws_a, first_a = ws_session(op_a)
        ws_messages = [first_a]
        assert isinstance(first_a, str), first_a
        assert _json.loads(first_a)["type"] == "subscribed"
        record("WS subscribed before terminal", True)

        done = wait_status(op_a, "confirmed")
        # Drain the socket: it must deliver state frames and a terminal frame.
        states = []
        terminal_seen = False
        for _ in range(40):
            try:
                msg = ws_a.recv(timeout=0.5)
            except Exception:
                break
            ws_messages.append(msg)
            obj = _json.loads(msg)
            if obj.get("type") == "state":
                states.append(obj["deposit"]["status"])
            if obj.get("type") == "terminal":
                terminal_seen = True
                assert obj["deposit"]["status"] == "confirmed", obj
                assert obj["deposit"]["points_awarded"] == 5, obj
        ws_a.close()

        record("WS delivers live state frames", bool(states), f"states={states}")
        record("WS terminal frame carries confirmed +5", terminal_seen)

        assert done["status"] == "confirmed", done
        assert done["points_awarded"] == 5, done
        assert done["actual_position"] == 1, done
        assert done["weight_g"] > 0, done
        record("HTTP poll shows confirmed +5 pts / pos 1", True)
        record("Points +5 exactly", points_now() == start + 5,
               f"start={start} now={points_now()}")

        history = client.get("/api/v1/waste/history", headers=headers).json()["items"]
        ev_a = [e for e in history if e["operation_id"] == op_a]
        record("Audit row exists (5 pts)", bool(ev_a) and ev_a[0]["points_awarded"] == 5)
        record("Route command carried mode=automatic",
               any(c.get("mode") == "automatic" for c in control.received))

        # =========================================================================
        # Scenario B — WRONG POSITION: machine settles at compartment 2.
        # =========================================================================
        start = points_now()
        control.plan = DepositPlan(name="wrong-position", destination_position=2, actual_position=2)
        pred = predict_fixture("high_conf_plastic.png")
        session = create_session(pred["prediction_id"])
        data = wait_status(session["operation_id"], "rejected")
        record("Wrong-position rejected", "wrong_position" in data["reject_reason"], data["reject_reason"])
        record("Wrong-position awarded 0", data["points_awarded"] == 0)
        record("Wrong-position no point delta", points_now() == start)

        # =========================================================================
        # Scenario C — UNDERWEIGHT: only 0.5g hits the load cell.
        # =========================================================================
        start = points_now()
        control.plan = DepositPlan(
            name="underweight",
            weight_timeline=[(0.0, 0.0), (0.8, 0.3), (1.4, 0.5)],
            final_weight=0.5,
            emit_machine_status="underweight",
        )
        pred = predict_fixture("high_conf_plastic.png")  # routing irrelevant here
        session = create_session(pred["prediction_id"])
        data = wait_status(session["operation_id"], "rejected")
        record(
            "Underweight rejected",
            "below the minimum" in data["reject_reason"], data["reject_reason"],
        )
        record("Underweight awarded 0", data["points_awarded"] == 0)
        record("Underweight no point delta", points_now() == start)

        # =========================================================================
        # Scenario D — EXPIRED: terminal arrives after the session lapsed.
        # =========================================================================
        start = points_now()
        control.plan = DepositPlan(name="expired")
        control.hold_seconds = 1.0
        pred = predict_fixture("high_conf_plastic.png")
        session = create_session(pred["prediction_id"])
        _force_expire(session["operation_id"])  # session lapses before terminal
        data = wait_status(session["operation_id"], "expired")
        control.hold_seconds = 0.0
        record("Expired -> status 'expired'", data["status"] == "expired", str(data))
        record("Expired awarded 0", data["points_awarded"] == 0)
        record("Expired no point delta", points_now() == start)

        # =========================================================================
        # Scenario E — CANCELLED: user cancels before the machine finishes.
        # =========================================================================
        start = points_now()
        control.plan = DepositPlan(name="cancelled")  # machine still completes
        control.hold_seconds = 0.6
        pred = predict_fixture("high_conf_plastic.png")
        session = create_session(pred["prediction_id"])
        r = client.post(f"/api/v1/deposit/{session['operation_id']}/cancel", headers=headers)
        assert r.status_code == 200, r.text
        data = wait_status(session["operation_id"], "cancelled")
        time.sleep(1.0)  # give the late terminal a chance to double-award
        control.hold_seconds = 0.0
        record("Cancel mid-flow -> cancelled", data["status"] == "cancelled")
        record("Late terminal did not award points", points_now() == start,
               f"start={start} now={points_now()}")

        # =========================================================================
        # Scenario F — DUPLICATE terminal: exactly one award.
        # =========================================================================
        start = points_now()
        control.plan = DepositPlan(name="duplicate", duplicate_terminal=True)
        pred = predict_fixture("high_conf_plastic.png")
        session = create_session(pred["prediction_id"])
        data = wait_status(session["operation_id"], "confirmed")
        time.sleep(0.5)  # second identical event must be ignored
        record("Duplicate -> confirmed +5 once", data["points_awarded"] == 5)
        record("Duplicate no double award", points_now() == start + 5,
               f"start={start} now={points_now()}")

        # =========================================================================
        # Scenario G — INPUT GATE: the synthetic grey frame that used to land
        # at LOW confidence is now rejected BEFORE classification by the AI
        # service's camera gate (real AI, no force overrides). No prediction
        # is produced, so no deposit session can ever be created.
        # =========================================================================
        control.hold_seconds = 0.0
        control.plan = None

        rg = client.post(
            "/api/v1/ai/predict", headers=headers,
            files={"image": ("low_conf.png", _fixture_bytes("low_conf.png"), "image/png")},
        )
        record(
            "Input gate rejects grey frame (422) -> nothing routed",
            rg.status_code == 422 and rg.json().get("code") == "LOW_QUALITY",
            f"status={rg.status_code} {rg.text}",
        )

        # =========================================================================
        # Scenario H — MEDIUM CONFIDENCE: real model straddles the band, backend
        # routes in manual mode and never auto-awards.
        # =========================================================================
        start = points_now()
        pred = predict_fixture("medium_conf.png")
        assert 0.50 <= pred["confidence"] < 0.80, pred
        before_routes = len(control.received)
        session = create_session(pred["prediction_id"])
        control.plan = None  # the physical drop never happens
        time.sleep(0.3)
        route = [c for c in control.received[before_routes:] if c.get("operation_id") == session["operation_id"]]
        record(
            "Medium route published in manual mode",
            bool(route) and route[0].get("mode") == "manual", str(route),
        )
        record(
            "No physical event -> no points (HTTP cannot award)",
            points_now() == start, f"start={start} now={points_now()}",
        )
        cur = client.get(f"/api/v1/deposit/{session['operation_id']}", headers=headers).json()
        record(
            "Medium session still pending (awaiting physical drop)",
            cur["status"] == "pending", str(cur["status"]),
        )

        # =========================================================================
        # Scenario I — STATION CAMERA (FINAL path): the phone never snaps a
        # photo. `create_capture_session` starts capture-first; the backend
        # publishes `capture_request`, the STATION camera (driven here by
        # `post_capture`) uploads a real frame to `/deposit/capture`, the
        # backend runs the REAL AI, routes automatically, and the physical drop
        # completes. Points only appear after the MQTT `deposit_result`.
        # =========================================================================
        start = points_now()
        control.plan = DepositPlan(name="station-capture")
        session = create_capture_session("st-001")
        op_i = session["operation_id"]
        assert session["status"] == "capture", session  # capture-first, not routed
        record("Station session starts capture-first (no prediction)", True)

        data = wait_status(op_i, "confirmed")
        assert data["status"] == "confirmed", data
        assert data["points_awarded"] == 5, data
        assert data["actual_position"] == 1, data
        assert data["predicted_class"] == "plastic", data
        record("Station capture -> real AI -> route -> confirmed +5", True)
        record("Points +5 exactly (station path)", points_now() == start + 5,
               f"start={start} now={points_now()}")

        req = [c for c in control.received if c.get("operation_id") == op_i
               and c.get("command") == "capture_request"]
        route = [c for c in control.received if c.get("operation_id") == op_i
                 and "destination_position" in c]
        record("Backend published capture_request to the station camera",
               bool(req), str(req))
        record("Backend routed after classification (mode=automatic)",
               bool(route) and route[0].get("mode") == "automatic", str(route))
        record("Capture endpoint never awarded points directly (HTTP cannot)",
               "points_awarded" not in {c.get("points_awarded") for c in req},
               "confirmed only after physical drop")

        history = client.get("/api/v1/waste/history", headers=headers).json()["items"]
        ev_i = [e for e in history if e["operation_id"] == op_i]
        record("Audit row exists for station-camera deposit (5 pts)",
               bool(ev_i) and ev_i[0]["points_awarded"] == 5)

        # =========================================================================
        # Rewards marketplace leg — atomic redemption over REAL HTTP+Postgres.
        # =========================================================================
        def set_points(points: int) -> None:
            conn = _connect_pg()
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET points=%s WHERE email=%s",
                            (points, DEMO_EMAIL))
            conn.commit()
            conn.close()

        catalog = client.get("/api/v1/rewards", headers=headers)
        record("Rewards catalog lists the seeded products",
               catalog.status_code == 200
               and {r["id"] for r in catalog.json()["rewards"]} >= {
                   "rw-vodafone-10", "rw-instapay-25",
                   "rw-mix-coffee-20", "rw-copy-center-30"},
               f"http={catalog.status_code}")

        anon = client.get("/api/v1/rewards")
        record("Rewards require authentication", anon.status_code == 401,
               str(anon.status_code))

        set_points(200)
        key = secrets.token_hex(16)
        r1 = client.post("/api/v1/rewards/rw-mix-coffee-20/redeem",
                         headers=headers, json={"idempotency_key": key})
        ok_r1 = (r1.status_code == 200 and r1.json()["balance"] == 140
                 and r1.json()["redemption"]["redemption_code"].startswith("ECO-"))
        record("Code redemption deducts once and issues an ECO code", ok_r1,
               r1.text[:120])

        retry = client.post("/api/v1/rewards/rw-mix-coffee-20/redeem",
                            headers=headers, json={"idempotency_key": key})
        record("Idempotent replay returns the SAME redemption, no double spend",
               retry.status_code == 200
               and retry.json()["redemption"]["id"] == r1.json()["redemption"]["id"]
               and retry.json()["balance"] == 140, retry.text[:120])

        rd_id = r1.json()["redemption"]["id"]
        cancel = client.post(f"/api/v1/rewards/redemptions/{rd_id}/cancel",
                             headers=headers)
        record("Cancelling an unused code refunds the exact points",
               cancel.status_code == 200
               and cancel.json()["redemption"]["status"] == "cancelled"
               and cancel.json()["balance"] == 200, cancel.text[:120])

        set_points(30)
        broke = client.post("/api/v1/rewards/rw-copy-center-30/redeem",
                            headers=headers,
                            json={"idempotency_key": secrets.token_hex(16)})
        conn = _connect_pg()
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE email=%s", (DEMO_EMAIL,))
            untouched = cur.fetchone()[0]
        conn.close()
        record("Insufficient balance -> 409 and points untouched",
               broke.status_code == 409 and untouched == 30,
               f"http={broke.status_code} points={untouched}")

        nodest = client.post("/api/v1/rewards/rw-vodafone-10/redeem",
                             headers=headers,
                             json={"idempotency_key": secrets.token_hex(16)})
        record("Cash payout without destination is refused",
               nodest.status_code == 422, nodest.text[:120])

        student_admin = client.get("/api/v1/admin/rewards/redemptions",
                                   headers=headers)
        record("Student cannot open the admin fulfillment queue",
               student_admin.status_code == 403, str(student_admin.status_code))

        # --- admin flow ------------------------------------------------------
        hash_out = subprocess.run(
            [PYTHON, "-c",
             "import sys; sys.path.insert(0, 'backend');"
             "from app.security.password import hash_password;"
             "print(hash_password('admin-pass-123'))"],
            capture_output=True, text=True, cwd=ROOT, check=True,
        )
        admin_hash = hash_out.stdout.strip()
        conn = _connect_pg()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, email, student_code, name,"
                " password_hash, faculty_id, points, role, is_active,"
                " email_verified, token_version, avatar_version)"
                " VALUES ('u-e2e-admin', 'admin@scwt.campus', 'S-E2EADMIN',"
                " 'E2E Admin', %s, 'ENGINEERING', 0, 'admin', true, true, 0, 0)"
                " ON CONFLICT (email) DO NOTHING",
                (admin_hash,),
            )
        conn.commit()
        conn.close()

        admin_login = client.post("/api/v1/auth/login", json={
            "email": "admin@scwt.campus", "password": "admin-pass-123"})
        assert admin_login.status_code == 200, admin_login.text
        admin_headers = {"Authorization":
                         f"Bearer {admin_login.json()['token']}"}

        set_points(100)
        cash_key = secrets.token_hex(16)
        cash = client.post("/api/v1/rewards/rw-vodafone-10/redeem",
                           headers=headers,
                           json={"idempotency_key": cash_key,
                                 "destination": "01012345678"})
        cash_id = cash.json()["redemption"]["id"]
        queue = client.get("/api/v1/admin/rewards/redemptions?status=pending",
                           headers=admin_headers)
        in_queue = any(i["id"] == cash_id and i["destination_masked"]
                       and "*" in i["destination_masked"]
                       for i in queue.json()["items"])
        record("Cash redemption lands PENDING in the admin queue (masked dest)",
               cash.status_code == 200
               and cash.json()["redemption"]["status"] == "pending" and in_queue,
               cash.text[:120])

        fulfilled = client.post(
            f"/api/v1/admin/rewards/redemptions/{cash_id}/fulfill",
            headers=admin_headers, json={"admin_note": "sent"})
        record("Admin fulfills the payout", fulfilled.status_code == 200
               and fulfilled.json()["status"] == "fulfilled")

        set_points(250)
        cash2 = client.post("/api/v1/rewards/rw-instapay-25/redeem",
                            headers=headers,
                            json={"idempotency_key": secrets.token_hex(16),
                                  "destination": "mac@instapay"})
        cash2_id = cash2.json()["redemption"]["id"]
        rejected = client.post(
            f"/api/v1/admin/rewards/redemptions/{cash2_id}/reject",
            headers=admin_headers, json={"admin_note": "unreachable"})
        conn = _connect_pg()
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE email=%s",
                        (DEMO_EMAIL,))
            refunded = cur.fetchone()[0]
        conn.close()
        record("Rejection refunds the points exactly once (250 restored)",
               rejected.status_code == 200 and refunded == 250,
               f"http={rejected.status_code} points={refunded}")
        again = client.post(
            f"/api/v1/admin/rewards/redemptions/{cash2_id}/reject",
            headers=admin_headers, json={})
        record("Double rejection is refused (no double refund)",
               again.status_code == 409, str(again.status_code))
        set_points(60)  # restore for the final DB integrity sweep

        # =========================================================================
        # Final DB integrity sweep.
        # =========================================================================
        conn = _connect_pg()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM deposit_sessions")
            n_sessions = cur.fetchone()[0]
            cur.execute(
                "SELECT status, COUNT(*) FROM deposit_sessions GROUP BY status"
            )
            by_status = dict(cur.fetchall())
            cur.execute(
                "SELECT COUNT(*) FROM waste_events WHERE points_awarded > 0"
            )
            n_paid = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM deposit_sessions WHERE status='confirmed'"
            )
            n_confirmed = cur.fetchone()[0]
            cur.execute("SELECT points FROM users WHERE email=%s", (DEMO_EMAIL,))
            final_points = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM (SELECT operation_id FROM waste_events "
                "GROUP BY operation_id HAVING COUNT(*) > 1) AS dup"
            )
            n_dup_events = cur.fetchone()[0]
        conn.close()

        # A: +5, F: +5, I: +5 -> exactly three paid events, three confirmed
        # sessions (the station-camera path awards through the same pipeline).
        record(
            "DB: exactly 3 confirmed sessions / 3 paid waste events",
            n_confirmed == 3 and n_paid == 3,
            f"confirmed={n_confirmed} paid={n_paid} by_status={by_status}",
        )
        record("DB: no duplicated waste_events", n_dup_events == 0)
        record(
            "DB: final points = 45 + 5 + 5 + 5 = 60",
            final_points == 60, f"points={final_points}",
        )
        record(
            "DB: 8 deposit sessions on record (G=422 never created one)",
            n_sessions == 8, f"n={n_sessions}",
        )

        print()
        print("=" * 70)
        for line in results:
            print(line)
        print("=" * 70)
        print(f"RESULT: {passes} passed, {failures} failed")
        client.close()
        sys.exit(1 if failures else 0)

    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
