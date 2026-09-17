#!/usr/bin/env python
"""Generate REAL development activity by driving the full real chain.

For every deposit this goes through the actual service chain — NO seeding of
activity, NO fake AI, NO offline fallback:

    real AI predict (ONNX via ai-service, quality gate honored)
      -> deposit session (backend + PostgreSQL)
      -> MQTT route command (mosquitto broker)
      -> hardware simulator executes a REAL plan (position match, weight
         ramp, beam, mechanical confirmation -> deposit_result event)
      -> backend validates and awards points atomically

Activity uses REAL station-capture images (ai-service/data/station_capture,
curated by the training pipeline). If the AI quality gate rejects an image
(NO_OBJECT / LOW_QUALITY / CORRUPT_IMAGE) it is RECORDED, never overridden.
A fresh real user is registered through the public /auth/register endpoint.

    scripts/generate_real_dev_activity.py [--attempts N] [--api 8100]

Prerequisites: the real dev stack up (scripts/dev_up.sh) + free MQTT command
delivery to the simulator (broker already running at :1886).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hardware-simulator"))

os.environ.setdefault("SIMULATOR_RAMP_STEP", "0")

import httpx  # noqa: E402

from hardware import Carriage, LoadCell  # noqa: E402
from scenarios import DepositPlan  # noqa: E402
from simulator import SCWTSimulator  # noqa: E402

MQTT_PORT = int(os.environ.get("MQTT_PORT", "1886"))
STATION_CODE = os.environ.get("STATION_CODE", "ST-001")
STATION_ID = os.environ.get("STATION_ID", "st-001")

CAPTURE_ROOT = ROOT / "ai-service" / "data" / "station_capture"
CLASSES = ("plastic", "metal", "paper", "other")


def _pick_images(per_class: int) -> list[tuple[str, Path]]:
    """Pick up to `per_class` REAL station photos per waste class (seeded so
    repeat runs are reproducible). Missing class dirs are skipped."""
    picked: list[tuple[str, Path]] = []
    for cls in CLASSES:
        d = CAPTURE_ROOT / cls
        if not d.is_dir():
            continue
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if not files:
            continue
        step = max(1, len(files) // per_class) if len(files) > per_class else 1
        taken = files[::step][:per_class]
        picked.extend((cls, p) for p in taken)
    return picked


class _ScenarioControl:
    """Hand-control hand-off: on each route command the simulator executes a
    valid plan that obeys the backend's routing decision (correct compartment,
    normal weight, beam + mechanical confirmation)."""

    def __init__(self) -> None:
        self._next: DepositPlan | None = None

    def arm_valid(self) -> None:
        self._next = DepositPlan(name="valid-plastic")

    def take(self) -> DepositPlan | None:
        plan = self._next
        self._next = None
        return plan


def _wait_status(client: httpx.Client, headers: dict, op_id: str,
                 timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/api/v1/deposit/{op_id}", headers=headers)
        if r.status_code == 200:
            last = r.json()
            if last["status"] in {"confirmed", "rejected", "expired", "cancelled"}:
                return last
        time.sleep(0.1)
    raise AssertionError(f"op {op_id} never reached terminal; last={last}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=12,
                        help="images to try per waste class (default 12)")
    parser.add_argument("--api", type=int, default=8100,
                        help="backend port (default 8100)")
    args = parser.parse_args()

    base = f"http://127.0.0.1:{args.api}"
    # Port health handled elsewhere; allow the stack already running.

    # ---- connect the simulator to the REAL broker ------------------------------
    from config import SimConfig
    cfg = SimConfig()
    cfg.broker_host = "127.0.0.1"
    cfg.broker_port = MQTT_PORT
    sim = SCWTSimulator(
        config=cfg,
        carriage=Carriage(initial_position=1, movement_time_per_step=0.0),
        load_cell=LoadCell(noise_grams=0, seed=11),
    )
    control = _ScenarioControl()

    def on_command(command: dict) -> None:
        plan = control.take()
        if plan is None:
            return
        try:
            sim.run_plan(
                command.get("operation_id") or "",
                command.get("destination_position"),
                plan,
            )
        except Exception:
            pass

    sim.mqtt.set_command_handler(on_command)
    sim.mqtt.start(cfg.command_topic(STATION_CODE))
    if not sim.mqtt.connected.wait(10):
        print("FATAL: simulator could not reach the broker on :%d" % MQTT_PORT)
        sys.exit(1)
    time.sleep(0.5)

    client = httpx.Client(base_url=base, timeout=30.0)

    # ---- register a REAL user through the public endpoint ----------------------
    email = f"dev.{int(time.time())}@student.recycle.dev"
    password = "DevPass!2345"
    r = client.post("/api/v1/auth/register", json={
        "name": "Dev User",
        "email": email,
        "password": password,
        "facultyId": "engineering",
    })
    if r.status_code != 201:
        print(f"FATAL: register failed: {r.status_code} {r.text}")
        sys.exit(1)
    # Registration creates the account only (never a session) — login now.
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": password})
    if r.status_code != 200:
        print(f"FATAL: login failed: {r.status_code} {r.text}")
        sys.exit(1)
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"[activity] registered real user {email} (points=0)")

    images = _pick_images(args.attempts)
    print(f"[activity] {len(images)} real station images queued "
          f"(={args.attempts} per class); gate rejections will be recorded, "
          "not overridden.")

    stats = {"gate_reject": 0, "confirmed": 0, "rejected": 0, "points": 0}
    by_class: dict[str, list[str]] = {c: [] for c in CLASSES}
    reject_codes: dict[str, int] = {}

    for expected_cls, img in images:
        label = f"{expected_cls}/{img.name}"
        blob = img.read_bytes()
        pred = client.post(
            "/api/v1/ai/predict", headers=headers,
            files={"image": (img.name, blob, "image/jpeg")},
        )
        if pred.status_code != 200:
            code = pred.json().get("code", f"http{pred.status_code}")
            reject_codes[code] = reject_codes.get(code, 0) + 1
            stats["gate_reject"] += 1
            print(f"  [gate:{code}] {label}")
            continue
        body = pred.json()
        assert body["source"] == "ai", body  # real model, no demo
        cls = body["predicted_class"]
        op_prefix = body["operation_id"]

        # Arm the plan BEFORE creating the session: the backend publishes the
        # route command synchronously during POST /deposit/session, and the
        # simulator must already hold a plan when it arrives.
        control.arm_valid()
        sess = client.post("/api/v1/deposit/session", headers=headers, json={
            "ai_prediction_id": body["prediction_id"],
            "station_id": STATION_ID,
        })
        if sess.status_code != 200:
            print(f"  [session-fail] {label}: {sess.status_code} {sess.text}")
            continue
        op_id = sess.json()["operation_id"]

        final = _wait_status(client, headers, op_id)
        ok = final["status"] == "confirmed"
        if ok:
            stats["confirmed"] += 1
            stats["points"] += final.get("points_awarded", 0)
            by_class.setdefault(cls, []).append(op_id)
            print(f"  [CONFIRMED +{final.get('points_awarded', 0)}] "
                  f"{label} -> {cls} {op_prefix}")
        else:
            stats["rejected"] += 1
            print(f"  [rejected:{final.get('status')}] {label} -> {cls} "
                  f"{final.get('reject_reason', '')}")

    print()
    print("=" * 70)
    print(f"REAL activity generated: {stats['confirmed']} confirmed deposits, "
          f"{stats['points']} points, "
          f"{stats['gate_reject']} gate rejections, {stats['rejected']} rejected")
    if reject_codes:
        print("Gate rejections by code:", json.dumps(reject_codes))
    for cls in CLASSES:
        n = len(by_class.get(cls, []))
        if n:
            print(f"  {cls:8s}: {n} confirmed")
    print("=" * 70)

    sim.mqtt.stop()
    client.close()
    sys.exit(0 if stats["confirmed"] > 0 else 1)


if __name__ == "__main__":
    main()