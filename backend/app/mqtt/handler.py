from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..services import DepositService, registry
from ..services.deposit_service import DuplicateDepositError, DepositEventError
from ..services.event_bus import event_bus
from ..services.station_registry import POSITIONS, StationSnapshot
from ..state import get_gateway

logger = logging.getLogger("recycle.mqtt.dispatch")


def install_handlers(gateway) -> None:
    """Wire the MQTT gateway callbacks to services. Terminal sensor events
    drive the authoritative deposit validation; state/heartbeat feed the live
    station registry; every terminal event fans out to WebSocket subscribers."""
    gateway.on_event(_handle_event)
    gateway.on_sensor(_handle_sensor)
    gateway.on_state(_handle_state)
    gateway.on_heartbeat(_handle_heartbeat)


def _handle_event(payload: dict) -> None:
    operation_id = payload.get("operation_id")
    if payload.get("event") == "deposit_result":
        db = SessionLocal()
        try:
            result = DepositService(RuntimePublishAdapter()).complete_from_event(db, payload)
            # Forward the AUTHORITATIVE serialized deposit (PostgreSQL-backed),
            # never the raw machine claim.
            event_bus.publish(operation_id, {"type": "terminal", "deposit": result})
        except DuplicateDepositError:
            logger.warning("[VALIDATION] duplicate terminal event ignored op=%s", operation_id)
        except DepositEventError as exc:
            logger.warning("[VALIDATION] invalid deposit event ignored: %s", exc)
        except Exception:
            logger.exception("[PARTICIPANT] error handling deposit event op=%s", operation_id)
        finally:
            db.close()
    else:
        # Machine state transitions are persisted as the deposit's live phase
        # and pushed to WebSocket subscribers as authoritative deposit states.
        if not operation_id:
            return
        db = SessionLocal()
        try:
            state = DepositService(RuntimePublishAdapter()).apply_machine_state(db, payload)
            if state is not None:
                event_bus.publish(operation_id, {"type": "state", "deposit": state})
        except Exception:
            logger.exception("[STATE] error applying machine state op=%s", operation_id)
        finally:
            db.close()


def _handle_sensor(payload: dict) -> None:
    _remember_station(payload)


def _handle_state(payload: dict) -> None:
    _remember_station(payload)


def _handle_heartbeat(station_id: str, payload: dict) -> None:
    logger.info("[STATION] %s heartbeat status=%s", station_id, payload.get("status"))
    _remember_station({**payload, "station_id": station_id})


def _remember_station(payload: dict) -> None:
    code = payload.get("station_id")
    if not code:
        return
    snap = registry.get(code)
    if snap is None:
        snap = StationSnapshot(
            station_id=code,
            code=code,
            name=code,
            status="online",
        )
        registry.register(snap)
    state = payload.get("state")
    status = payload.get("status") or "online"
    registry.update(
        code,
        status=_status_of(status),
        state=state or snap.state,
        carriage_position=payload.get("carriage_position", snap.carriage_position),
        current_position=payload.get("current_position", snap.current_position),
        door_state=payload.get("door_state", snap.door_state),
        weight_grams=payload.get("weight_grams", snap.weight_grams),
        weight_stable=payload.get("weight_stable", snap.weight_stable),
        beam_broken=payload.get("beam_broken", snap.beam_broken),
        operation_id=payload.get("operation_id", snap.operation_id),
    )


def _status_of(status: str) -> str:
    return "online" if status not in ("offline", "error") else status


class RuntimePublishAdapter:
    """Publisher for the deposit service that forwards commands through the
    active gateway (dispatch runs in the MQTT thread; publishing is safe)."""

    def publish_route(self, station_id, operation_id, destination_position, mode) -> None:
        gw = get_gateway()
        if gw is None:  # pragma: no cover
            logger.error("route command dropped for %s (no gateway)", operation_id)
            return
        gw.publish_route(station_id, operation_id, destination_position, mode)

    def publish_capture_request(self, station_id, operation_id) -> None:
        gw = get_gateway()
        if gw is None:  # pragma: no cover
            logger.error("capture_request dropped for %s (no gateway)", operation_id)
            return
        gw.publish_capture_request(station_id, operation_id)