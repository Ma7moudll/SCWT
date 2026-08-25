"""Paho MQTT client wrapper for the simulated ESP32.

Publishes on the documented station topics and subscribes to `.../command`.
Behaviour is protocol-identical to the future ESP32 firmware."""

from __future__ import annotations

import json
import logging
import threading
from typing import Callable

import paho.mqtt.client as mqtt

logger = logging.getLogger("sim.mqtt")


class SimulatorMqttClient:
    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        client_id: str,
        username: str | None = None,
        password: str | None = None,
        tls: bool = False,
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.connected = threading.Event()
        self._on_command: Callable[[dict], None] | None = None

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311
        )
        if username:
            self._client.username_pw_set(username, password)
        if tls:
            self._client.tls_set()  # system trust store, no bypass
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(1, 30)
        self._thread: threading.Thread | None = None

    def set_command_handler(self, handler: Callable[[dict], None]) -> None:
        self._on_command = handler

    def start(self, command_topic: str) -> None:
        self._thread = threading.Thread(target=self._run, name="sim-mqtt", daemon=True)
        self._thread.start()
        self.command_topic = command_topic

    def _run(self) -> None:
        import time

        while True:
            try:
                self._client.connect_async(self.broker_host, self.broker_port, keepalive=30)
                self._client.loop_forever(retry_first_connection=True)
                break
            except Exception:
                logger.exception("MQTT connection error; retrying")
                time.sleep(2)

    def _on_connect(self, _c, _u, _f, reason_code, _p) -> None:
        ok = reason_code == 0  # int (v3.1.1) or ReasonCode (v5); both == 0 for success
        if ok:
            self.connected.set()
            logger.info("Connecting to MQTT... OK")
            self._client.subscribe(getattr(self, "command_topic", "#"), qos=1)

    def _on_disconnect(self, _c, _u, _f, reason_code, _p) -> None:
        self.connected.clear()
        logger.warning("[MQTT] disconnected reason=%s", reason_code)

    def _on_message(self, _c, _u, msg) -> None:
        logger.info("[MQTT] message topic=%s payload=%s", msg.topic, msg.payload.decode("utf-8", "replace"))
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except ValueError:
            return
        if isinstance(payload, dict) and self._on_command:
            self._on_command(payload)

    # -- publishing ------------------------------------------------------------

    def publish(self, topic: str, payload: dict, qos: int = 1) -> None:
        self._client.publish(topic, json.dumps(payload), qos=qos)
        logger.info("[SEND] %s <- %s", topic, payload)

    def stop(self) -> None:
        try:
            self._client.disconnect()
        except Exception:  # pragma: no cover
            pass