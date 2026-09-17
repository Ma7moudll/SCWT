"""Start the REAL service stack for the on-device STATION-CAMERA E2E.

This is the host-side companion to the mobile integration test
(`mobile/integration_test/station_capture_e2e_test.dart`). It starts:

  * mosquitto broker           (port 1886)
  * ai-service (real model)    (port 8052)
  * backend + PostgreSQL       (port 8100, MQTT -> broker, AI -> ai-service)
  * hardware simulator         (acts as the station: answers `capture_request`
    by uploading a REAL frame to `POST /api/v1/deposit/capture`, then performs
    the physical drop over MQTT)

The stack keeps running so the emulator/device integration test can talk to it;
Ctrl-C tears it down. The phone under test NEVER snaps or uploads a photo — it
only creates a capture-first session and observes the terminal status.

    scripts/station_capture_e2e_stack.py

Prerequisites: PostgreSQL on localhost:5432 (role recycle/recycle,
db scwt_db_e2e), mosquitto at /opt/homebrew/sbin/mosquitto, free ports
1886/8052/8100, and the trained model at ai-service/models/model.onnx. The
easiest DB bootstrap is:

    docker compose -f infra/docker-compose.yml up -d db
    createdb -U scwt scwt_e2e      # then run the e2e once to create schema
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / ".venv" / "bin" / "python")
MOSQUITTO_BIN = Path("/opt/homebrew/sbin/mosquitto")
AI_MODEL_PATH = ROOT / "ai-service" / "models" / "model.onnx"

HOST = "0.0.0.0"  # reachable from the emulator AND from LAN devices
BIND = "127.0.0.1"
MQTT_PORT = 1886
AI_PORT = 8052
API_PORT = 8100

DB_URL = (
    "postgresql+psycopg2://scwt:scwt@localhost:5432/scwt_db_e2e"
)
JWT_SECRET = "e2e-secret-not-for-prod"

DEMO_EMAIL = "demo@scwt.app"
DEMO_PASSWORD = "demo123"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, port)) != 0


def _wait_port(port: int, bind: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((bind, port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} never came up")


def main() -> None:
    assert MOSQUITTO_BIN.exists(), f"mosquitto not found at {MOSQUITTO_BIN}"
    assert AI_MODEL_PATH.exists(), f"trained model not found at {AI_MODEL_PATH}"
    for p in (MQTT_PORT, AI_PORT, API_PORT):
        if not _port_free(p):
            raise SystemExit(f"port {p} busy — stop the running service")

    procs: list[subprocess.Popen] = []
    try:
        # -- mosquitto (AUTHENTICATED — parity with production) ------------------
        import secrets

        mqtt_user = "backend"
        mqtt_pass = secrets.token_urlsafe(24)
        passwd_file = "/tmp/station_e2e_mosquitto.passwd"
        acl_file = "/tmp/station_e2e_mosquitto.acl"
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
            f"listener {MQTT_PORT} 0.0.0.0\n"
            "allow_anonymous false\n"
            f"password_file {passwd_file}\n"
            f"acl_file {acl_file}\n"
            "max_queued_messages 1000\n"
            "message_size_limit 0\n"
        )
        conf.close()
        procs.append(subprocess.Popen(
            [str(MOSQUITTO_BIN), "-c", conf.name, "-v"],
            stdout=open("/tmp/station_e2e_mosquitto.log", "w"),
            stderr=subprocess.STDOUT,
        ))
        _wait_port(MQTT_PORT, "127.0.0.1")
        print(f"[stack] mosquitto listening on :{MQTT_PORT} (authenticated)")

        # -- ai-service (REAL model) ---------------------------------------------
        env = dict(os.environ)
        env.update({
            "PYTHONPATH": str(ROOT / "ai-service"),
            "AI_SERVICE_CLASSIFIER": "real",
            "AI_MODEL_PATH": str(AI_MODEL_PATH),
            # Poison dev overrides to prove the real path ignores them.
            "DEVELOPMENT_FORCE_CLASS": "plastic",
            "DEVELOPMENT_FORCE_CONFIDENCE": "0.99",
        })
        procs.append(subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "app.main:app", "--host", BIND,
             "--port", str(AI_PORT), "--log-level", "warning"],
            cwd=str(ROOT / "ai-service"), env=env,
            stdout=open("/tmp/station_e2e_ai.log", "w"),
            stderr=subprocess.STDOUT,
        ))
        _wait_port(AI_PORT, BIND)
        print(f"[stack] ai-service on {BIND}:{AI_PORT} (classifier=real)")

        # -- backend -------------------------------------------------------------
        env = dict(os.environ)
        env.update({
            "PYTHONPATH": str(ROOT / "backend"),
            "DATABASE_URL": DB_URL,
            "MQTT_BROKER_HOST": "127.0.0.1",
            "MQTT_BROKER_PORT": str(MQTT_PORT),
            "MQTT_USERNAME": mqtt_user,
            "MQTT_PASSWORD": mqtt_pass,
            "AI_SERVICE_URL": f"http://{BIND}:{AI_PORT}",
            "JWT_SECRET": JWT_SECRET,
            "SEED_ON_STARTUP": "true",
            "SEED_DEMO_USER": "true",
            "DEBUG": "false",
        })
        procs.append(subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "app.main:app", "--host", HOST,
             "--port", str(API_PORT), "--log-level", "info"],
            cwd=str(ROOT / "backend"), env=env,
            stdout=open("/tmp/station_e2e_backend.log", "w"),
            stderr=subprocess.STDOUT,
        ))
        _wait_port(API_PORT, HOST)
        print(f"[stack] backend on {HOST}:{API_PORT}")

        # -- hardware simulator (the STATION: camera + carriage + sensors) --------
        env = dict(os.environ)
        env.update({
            "PYTHONPATH": str(ROOT / "hardware-simulator"),
            "MQTT_BROKER_HOST": "127.0.0.1",
            "MQTT_BROKER_PORT": str(MQTT_PORT),
            "MQTT_USERNAME": mqtt_user,
            "MQTT_PASSWORD": mqtt_pass,
            "BACKEND_URL": f"http://{BIND}:{API_PORT}",
            "STATION_API_KEY": "dev-station-key",
            # Answer capture_request with a real frame from this class.
            "SIMULATOR_CAPTURE_CLASS": "plastic",
        })
        procs.append(subprocess.Popen(
            [PYTHON, "-m", "simulator"],
            cwd=str(ROOT / "hardware-simulator"), env=env,
            stdout=open("/tmp/station_e2e_simulator.log", "w"),
            stderr=subprocess.STDOUT,
        ))
        time.sleep(4.0)  # let the simulator connect + register its heartbeat
        print(f"[stack] hardware simulator on MQTT :{MQTT_PORT} (capture=plastic)")

        print()
        print("Services are running. From the Android EMULATOR the app reaches")
        print("them via API_BASE_URL=http://10.0.2.2:8100/api/v1; from a physical")
        print("device use this machine's LAN IP instead. Press Ctrl-C to stop.")
        print()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("[stack] shutting down")
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
    sys.exit(main())
