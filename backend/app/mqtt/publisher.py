"""Convenience publisher that routes commands through the active MQTT gateway
when configured (falls back to a no-op so the API works with pure HTTP
tests and the legacy offline bridge)."""
from __future__ import annotations

import logging

from ..services.deposit_service import CommandPublisher
from ..state import get_gateway

logger = logging.getLogger("recycle.mqtt")


class RuntimePublisher(CommandPublisher):
    def publish_route(
        self, station_id: str, operation_id: str, destination_position: int, mode: str
    ) -> None:
        gw = get_gateway()
        if gw is None:
            logger.warning(
                "[MQTT] no gateway configured; route command not published "
                "operation=%s destination=%s", operation_id, destination_position,
            )
            return
        gw.publish_route(station_id, operation_id, destination_position, mode)

    def publish_capture_request(self, station_id: str, operation_id: str) -> None:
        gw = get_gateway()
        if gw is None:
            logger.warning(
                "[MQTT] no gateway configured; capture_request not published "
                "operation=%s", operation_id,
            )
            return
        gw.publish_capture_request(station_id, operation_id)