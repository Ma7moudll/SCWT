"""MQTT gateway for the backend.

Subscribes to the station topics owned by the hardware/ESP32 and dispatches
sensor & event telemetry into the deposit service and station registry. It is
also the publisher that sends routing commands to the station.

Topic contract (see docs/mqtt-contract.md):
  scwt/stations/{code}/command    backend -> station
  scwt/stations/{code}/state      station -> backend
  scwt/stations/{code}/sensor     station -> backend
  scwt/stations/{code}/event      station -> backend
  scwt/stations/{code}/heartbeat  station -> backend
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import paho.mqtt.client as mqtt

from ..config import settings

logger = logging.getLogger("recycle.mqtt")


class MqttGateway:
    def __init__(
        self,
        broker_host: str | None = None,
        broker_port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
    ) -> None:
        self.broker_host = broker_host or settings.mqtt_broker_host
        self.broker_port = broker_port or settings.mqtt_broker_port
        self.username = username if username is not None else settings.mqtt_username
        self.password = password if password is not None else settings.mqtt_password
        self.client_id = client_id or settings.mqtt_client_id
        self.prefix = settings.mqtt_topic_prefix
        self.connected = threading.Event()
        self._thread: threading.Thread | None = None

        self._on_event: Callable[[dict], None] | None = None
        self._on_sensor: Callable[[dict], None] | None = None
        self._on_state: Callable[[dict], None] | None = None
        self._on_heartbeat: Callable[[str, dict], None] | None = None

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, protocol=mqtt.MQTTv311
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        if settings.mqtt_tls:
            # TLS with the system trust store: certificate validation is ALWAYS
            # on (no insecure bypasses). HiveMQ Cloud serves a publicly trusted
            # chain, so no custom CA bundle is needed.
            self._client.tls_set()  # type: ignore[no-untyped-call]
            # Default to the TLS listener unless the caller pinned a port.
            if broker_port is None:
                self.broker_port = settings.mqtt_tls_port
        self._client.reconnect_delay_set(1, 30)

    # -- setup -----------------------------------------------------------------

    def on_event(self, cb: Callable[[dict], None]) -> "MqttGateway":
        self._on_event = cb
        return self

    def on_sensor(self, cb: Callable[[dict], None]) -> "MqttGateway":
        self._on_sensor = cb
        return self

    def on_state(self, cb: Callable[[dict], None]) -> "MqttGateway":
        self._on_state = cb
        return self

    def on_heartbeat(self, cb: Callable[[str, dict], None]) -> "MqttGateway":
        self._on_heartbeat = cb
        return self

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_forever, name="mqtt-gateway", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        except Exception:  # pragma: no cover
            pass

    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self.connected.wait(timeout)

    def _run_forever(self) -> None:
        while True:
            try:
                self._client.connect_async(self.broker_host, self.broker_port, keepalive=30)
                self._client.loop_forever(retry_first_connection=True)
            except Exception:
                logger.exception("MQTT connection error; retrying in 3s")
                time.sleep(3)

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        # paho 2.x passes an int (MQTT 3.1.1) or a ReasonCode (MQTT 5);
        # comparing to 0 is correct for both (ReasonCode.__eq__ handles ints).
        ok = reason_code == 0
        if ok:
            self.connected.set()
            logger.info(
                "[MQTT] connected to %s:%s", self.broker_host, self.broker_port,
            )
            self._subscribe()
        else:
            logger.error("[MQTT] connection refused: %s", reason_code)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        disconnected = reason_code != 0
        self.connected.clear()
        logger.warning("[MQTT] disconnected (code=%s)", reason_code if disconnected else 0)

    def _subscribe(self) -> None:
        for suffix in ("event", "sensor", "state", "heartbeat"):
            topic = f"{self.prefix}/+/{suffix}"
            self._client.subscribe(topic, qos=1)
            logger.info("[MQTT] subscribed %s", topic)

    def _on_message(self, _client, _userdata, msg) -> None:
        topic: str = msg.topic
        suffix = topic.rsplit("/", 1)[-1]
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("[MQTT] non-JSON payload on %s", topic)
            return
        if not isinstance(payload, dict):
            return
        station_id = payload.get("station_id") or topic.split("/")[1]
        if suffix == "event":
            if self._on_event:
                self._on_event({**payload, "station_id": station_id})
        elif suffix == "sensor":
            if self._on_sensor:
                self._on_sensor({**payload, "station_id": station_id})
        elif suffix == "state":
            if self._on_state:
                self._on_state({**payload, "station_id": station_id})
        elif suffix == "heartbeat":
            if self._on_heartbeat:
                self._on_heartbeat(station_id, payload)

    # -- publishing ---------------------------------------------------------------

    def publish_command(self, station_code: str, command: dict) -> None:
        topic = f"{self.prefix}/{station_code}/command"
        self._client.publish(topic, json.dumps(command), qos=1)
        logger.info("[MQTT] command sent topic=%s command=%s", topic, command.get("command"))

    def publish_route(
        self, station_id: str, operation_id: str, destination_position: int, mode: str
    ) -> None:
        self.publish_command(
            station_id,
            {
                "operation_id": operation_id,
                "command": "route",
                "destination_position": destination_position,
                "mode": mode,
            },
        )

    def publish_capture_request(self, station_id: str, operation_id: str) -> None:
        self.publish_command(
            station_id,
            {
                "operation_id": operation_id,
                "command": "capture_request",
            },
        )