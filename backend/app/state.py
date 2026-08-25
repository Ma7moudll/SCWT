"""Process-wide singleton state: the active MQTT gateway (configured during
startup, swapable in tests) shared by routers, dispatch and the WS bridge."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..mqtt import MqttGateway

_active: "MqttGateway | None" = None


def configure_gateway(gateway: Any | None) -> None:
    global _active
    _active = gateway


def get_gateway() -> Any | None:
    return _active