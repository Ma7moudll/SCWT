"""Shared fixtures for full-chain MQTT integration tests.

Spins up a REAL authenticated mosquitto broker on :1884 (parity with
production) with two identities:

    backend        -- full control of the station tree (what the gateway uses;
                      credentials MUST match backend/tests/conftest.py env).
    station-st-001 -- least-privilege station identity used by the security
                      matrix tests to prove the broker enforces the ACL.
"""
from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

MOSQUITTO_BIN = Path("/opt/homebrew/sbin/mosquitto")
PASSWD_BIN = Path("/opt/homebrew/bin/mosquitto_passwd")
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1884  # must match backend/tests/conftest.py env
BROKER_USER = "backend"
BROKER_PASS = "itest-broker-pass"  # must match backend/tests/conftest.py env

# Least-privilege station identity (mirrors infra/mosquitto/acl pattern).
STATION_USER = "station-st-001"
STATION_PASS = "station-itest-pass"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((BROKER_HOST, port)) != 0


@pytest.fixture(scope="module")
def broker(tmp_path_factory):
    if not MOSQUITTO_BIN.exists():
        pytest.skip("mosquitto not installed (expect /opt/homebrew/sbin/mosquitto)")
    if not PASSWD_BIN.exists():
        pytest.skip("mosquitto_passwd not installed")

    if not _port_free(BROKER_PORT):
        pytest.skip(
            f"TCP {BROKER_PORT} is already in use (dev stack mosquitto?). "
            "Stop the dev broker before running the integration suite."
        )

    passwd_file = tmp_path_factory.mktemp("broker") / "passwd"
    subprocess.run(
        [str(PASSWD_BIN), "-b", "-c", str(passwd_file), BROKER_USER, BROKER_PASS],
        check=True,
    )
    subprocess.run(
        [str(PASSWD_BIN), "-b", str(passwd_file), STATION_USER, STATION_PASS],
        check=True,
    )

    acl_file = tmp_path_factory.mktemp("broker") / "acl"
    acl_file.write_text(
        f"user {BROKER_USER}\n"
        f"topic readwrite ecolamp/stations/#\n\n"
        f"# Least privilege: ST-001 may only touch its own topics.\n"
        f"user {STATION_USER}\n"
        f"topic read ecolamp/stations/st-001/command\n"
        f"topic read ecolamp/stations/st-001/capture_request\n"
        f"topic write ecolamp/stations/st-001/event\n"
        f"topic write ecolamp/stations/st-001/sensor\n"
        f"topic write ecolamp/stations/st-001/state\n"
        f"topic write ecolamp/stations/st-001/heartbeat\n"
    )

    conf = tmp_path_factory.mktemp("broker") / "mosquitto.conf"
    conf.write_text(
        f"listener {BROKER_PORT}\n"
        "allow_anonymous false\n"
        f"password_file {passwd_file}\n"
        f"acl_file {acl_file}\n"
        "max_queued_messages 1000\n"
        "message_size_limit 0\n"
    )

    proc = subprocess.Popen(
        [str(MOSQUITTO_BIN), "-c", str(conf), "-v"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.skip("mosquitto exited immediately (config/port problem)")
        if not _port_free(BROKER_PORT):
            break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("mosquitto did not start on port %d" % BROKER_PORT)

    time.sleep(0.5)  # let the listener fully accept subscriptions
    yield {"host": BROKER_HOST, "port": BROKER_PORT}
    proc.terminate()
    proc.wait(timeout=10)


def mosquitto_pub(topic: str, payload: str, user: str, password: str,
                  timeout: float = 10.0) -> int:
    """Publish one QoS 1 message; return the process exit code."""
    try:
        return subprocess.run(
            [
                "/opt/homebrew/bin/mosquitto_pub",
                "-h", BROKER_HOST, "-p", str(BROKER_PORT),
                "-u", user, "-P", password,
                "-q", "1",
                "-t", topic,
                "-m", payload,
            ],
            capture_output=True, text=True, timeout=timeout,
        ).returncode
    except subprocess.TimeoutExpired:
        return 124  # treat a hang as a failure (no PUBACK == denied)
