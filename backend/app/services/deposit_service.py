"""Deposit lifecycle: session creation, MQTT routing command issuance, and
authoritative validation of the physical sensor event that closes a session.

The ONLY way a deposit earns points is `complete_from_event(...)`, which is
triggered by a real MQTT event published by the simulator/ESP32 firmware. The
HTTP layer can create and cancel sessions but can never award points.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AiPrediction, DepositSession, RoutingPolicy, Station, User
from ..repositories import DepositRepository
from .ai_client import AiGateRejection, AiWireError
from .points_transaction import award_points, record_rejection
from .predict_service import PredictService
from .seed import next_operation_id

logger = logging.getLogger("recycle.deposit")

CAPTURE = "capture"
ANALYZING = "analyzing"
CONFIRMED = "confirmed"
REJECTED = "rejected"
CANCELLED = "cancelled"
EXPIRED = "expired"

TERMINAL = {CONFIRMED, REJECTED, CANCELLED, EXPIRED}

# Machine states (published by the ESP32/simulator as `state_changed` events)
# mapped to the persisted deposit status. Rank keeps transitions monotonic: a
# late telemetry frame can never regress a session to an earlier phase.
_MACHINE_TO_STATUS = {
    "ROUTING": "routing",
    "MOVING": "moving",
    "POSITIONED": "ready",
    "READY_FOR_DEPOSIT": "ready",
    "DETECTING": "detecting",
    "MEASURING": "measuring",
}
_STATUS_RANK = {
    CAPTURE: -2,
    ANALYZING: -1,
    "pending": 0,
    "routing": 1,
    "moving": 2,
    "ready": 3,
    "detecting": 4,
    "measuring": 5,
}

_MACHINE_REASONS = {
    "wrong_position": "the item did not reach the expected compartment",
    "underweight": "the recorded weight was below the minimum",
    "jam": "the carriage jammed",
    "timeout": "the operation timed out",
    "sensor_error": "a sensor reported an error",
}


class CommandPublisher(Protocol):
    def publish_route(
        self,
        station_id: str,
        operation_id: str,
        destination_position: int,
        mode: str,
    ) -> None: ...

    def publish_capture_request(self, station_id: str, operation_id: str) -> None: ...


def _utcnow() -> datetime:
    # AWARE UTC is written to the DB: `DateTime(timezone=True)` means
    # PostgreSQL stores the absolute instant regardless of the session
    # TimeZone (writing naive datetimes would shift by the server offset).
    # Reads are normalised to naive UTC by `_naive_utc` so comparisons and
    # ISO-8601 output are identical on Postgres and SQLite.
    return datetime.now(timezone.utc)


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Converts any aware datetime to naive UTC (no-op for naive values) so
    comparisons and ISO-8601 output are identical on Postgres and SQLite."""
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _ttl() -> timedelta:
    return timedelta(seconds=settings.deposit_session_ttl_seconds)


class DepositEventError(ValueError):
    pass


class DuplicateDepositError(DepositEventError):
    pass


class DepositService:
    def __init__(
        self,
        publisher: CommandPublisher,
        predictor: PredictService | None = None,
    ) -> None:
        self.publisher = publisher
        self.repo = DepositRepository()
        self.predictor = predictor

    # -- session creation ------------------------------------------------------

    def create_session(
        self,
        db: Session,
        user: User,
        prediction_id: str | None = None,
        station_id: str = "st-001",
    ) -> DepositSession:
        """Creates a tracked deposit session and routes it.

        Legacy phone-camera path: pass `prediction_id` and the session routes
        straight away (points are still never awarded here).

        Station-camera path (`prediction_id=None`, the FINAL architecture):
        the session is created capture-first — the STATION camera supplies the
        frame via `POST /api/v1/deposit/capture`, the backend classifies it and
        only then issues the routing command."""
        station = db.get(Station, station_id)
        if station is None:
            raise ValueError("Station not found")
        if prediction_id is None:
            return self._create_capture_session(db, user, station)

        prediction = db.get(AiPrediction, prediction_id)
        if prediction is None:
            raise ValueError("AI prediction not found")
        if prediction.user_id != user.id:
            raise ValueError("AI prediction does not belong to this user")
        if _naive_utc(prediction.expires_at) < _naive_utc(_utcnow()):
            raise ValueError("AI prediction expired")

        # Confidence policy — enforced by the backend, never the client.
        if prediction.confidence_level == "low":
            raise ValueError(
                "Confidence too low to route. Please retake the photo."
            )

        policy = db.execute(
            select(RoutingPolicy).where(RoutingPolicy.waste_class == prediction.predicted_class)
        ).scalar_one_or_none()
        if policy is None:
            raise ValueError(
                f"No routing policy for class '{prediction.predicted_class}'. "
                "Contact an administrator."
            )

        now = _utcnow()
        session = DepositSession(
            operation_id=next_operation_id(db),
            user_id=user.id,
            station_id=station.id,
            ai_prediction_id=prediction.id,
            routing_policy_id=policy.id,
            potential_points=policy.potential_points,
            status="pending",
            expected_class=prediction.predicted_class,
            expected_position=policy.position,
            confidence=prediction.confidence,
            confidence_level=prediction.confidence_level,
            created_at=now,
            expires_at=now + _ttl(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        mode = "automatic" if prediction.confidence_level == "high" else "manual"
        self.publisher.publish_route(
            station_id=station.station_code,
            operation_id=session.operation_id,
            destination_position=policy.position,
            mode=mode,
        )
        logger.info(
            "[ROUTING] operation=%s class=%s destination=%s mode=%s",
            session.operation_id, prediction.predicted_class, policy.position, mode,
        )
        return session

    def _create_capture_session(self, db: Session, user: User, station: Station) -> DepositSession:
        """Capture-first session: no prediction yet, the station camera takes
        the frame. Issues `capture_request` so the camera snaps immediately."""
        now = _utcnow()
        session = DepositSession(
            operation_id=next_operation_id(db),
            user_id=user.id,
            station_id=station.id,
            ai_prediction_id=None,
            routing_policy_id=None,
            potential_points=0,
            status=CAPTURE,
            expected_class=None,
            expected_position=None,
            created_at=now,
            expires_at=now + _ttl(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        self.publisher.publish_capture_request(station.station_code, session.operation_id)
        logger.info(
            "[CAPTURE-REQUEST] operation=%s station=%s",
            session.operation_id, station.station_code,
        )
        return session

    # -- station camera capture --------------------------------------------------

    def handle_capture(
        self,
        db: Session,
        operation_id: str,
        station_code: str,
        image_bytes: bytes,
        image_url: str | None = None,
    ) -> dict:
        """Receives a frame snapped by the STATION camera, classifies it with the
        real AI service, attaches the prediction to the session and routes —
        exactly like the legacy phone-camera path but driven by the backend.

        Never awards points: completion still requires the physical MQTT event.
        A low-confidence frame cannot route; the session is closed as rejected
        and no route command is issued."""
        session = self.repo.get_by_operation_id(db, operation_id)
        if session is None:
            raise ValueError("Deposit not found")
        station = db.execute(
            select(Station).where(
                or_(Station.station_code == station_code, Station.id == station_code)
            )
        ).scalar_one_or_none()
        if station is None or station.id != session.station_id:
            raise ValueError("Station mismatch")
        if session.status in TERMINAL:
            raise ValueError(f"Deposit already {session.status}")

        session.status = ANALYZING
        db.commit()

        user = db.get(User, session.user_id)
        if user is None:
            raise ValueError("Deposit user no longer exists")

        predictor = self.predictor or PredictService()
        try:
            pred = predictor.predict(db, user, image_bytes, image_url=image_url)
        except AiGateRejection:
            # The AI camera gate rejected the FRAME (bad lighting, blur, corrupt,
            # no object) BEFORE classification: no prediction persisted, session
            # stays capture-able so the station camera can retake.
            session.status = CAPTURE
            db.commit()
            raise
        except AiWireError:
            # The AI service itself is unavailable/errored (network, timeout,
            # bad response). No prediction persisted; the session returns to
            # `capture` so the camera can retake once the service is back.
            session.status = CAPTURE
            db.commit()
            raise

        policy = db.execute(
            select(RoutingPolicy).where(RoutingPolicy.waste_class == pred["predicted_class"])
        ).scalar_one_or_none()
        if policy is None:
            raise ValueError(
                f"No routing policy for class '{pred['predicted_class']}'. "
                "Contact an administrator."
            )
        session.ai_prediction_id = pred["prediction_id"]
        session.routing_policy_id = policy.id
        session.expected_class = pred["predicted_class"]
        session.expected_position = pred["destination_position"]
        session.potential_points = pred["potential_points"]
        session.confidence = pred["confidence"]
        session.confidence_level = pred["confidence_level"]

        if pred["confidence_level"] == "low":
            session.status = REJECTED
            session.reject_reason = (
                "Confidence too low to route. Please retry at the station."
            )
            session.completed_at = _utcnow()
            db.commit()
            db.refresh(session)
            logger.info(
                "[CAPTURE] rejected operation=%s class=%s conf=%.2f",
                operation_id, pred["predicted_class"], pred["confidence"],
            )
            return _serialize(session)

        mode = "automatic" if pred["confidence_level"] == "high" else "manual"
        session.status = "pending"
        db.commit()
        self.publisher.publish_route(
            station_id=station.station_code,
            operation_id=session.operation_id,
            destination_position=policy.position,
            mode=mode,
        )
        db.refresh(session)
        logger.info(
            "[CAPTURE] routed operation=%s class=%s destination=%s mode=%s",
            session.operation_id, pred["predicted_class"], policy.position, mode,
        )
        return _serialize(session)

    # -- cancellation ------------------------------------------------------------

    def cancel(self, db: Session, user: User, operation_id: str) -> DepositSession:
        session = self.repo.get_by_operation_id(db, operation_id)
        if session is None or session.user_id != user.id:
            raise ValueError("Deposit not found")
        if session.status in TERMINAL:
            raise ValueError(f"Cannot cancel deposit in state '{session.status}'")
        session.status = CANCELLED
        session.completed_at = _utcnow()
        db.commit()
        db.refresh(session)
        return session

    # -- machine state transitions ------------------------------------------------

    def apply_machine_state(self, db: Session, event: dict) -> dict | None:
        """Persists the deposit's live phase from a machine `state_changed`
        event and returns the serialized deposit for realtime subscribers.

        Returns None when there is nothing to persist (unknown operation,
        unknown machine state, or the session is already terminal). Never
        touches points — only the authoritative `deposit_result` event can."""
        operation_id = event.get("operation_id")
        if not operation_id:
            return None
        machine_state = (event.get("state") or "").upper()
        target = _MACHINE_TO_STATUS.get(machine_state)
        if target is None:
            return None

        session = self.repo.get_by_operation_id(db, operation_id)
        if session is None or session.status in TERMINAL:
            return None
        if _STATUS_RANK.get(target, 0) <= _STATUS_RANK.get(session.status, 0):
            return None

        session.status = target
        db.commit()
        db.refresh(session)
        return _serialize(session)

    # -- completion via MQTT sensor events ------------------------------------------

    def complete_from_event(self, db: Session, event: dict) -> dict:
        """Backend-side validation of a physical `deposit_result` MQTT event.

        Applies EVERY gate from the spec before any points move: session
        exists / not expired / operation never completed / station match /
        expected position / minimum weight / weight stable / beam event valid /
        carriage reached target / mechanical confirmation."""
        operation_id = event.get("operation_id")
        if not operation_id:
            raise DepositEventError("missing operation_id")

        session = self.repo.get_by_operation_id(db, operation_id)
        if session is None:
            raise DepositEventError("unknown operation_id")

        # station match: MQTT payloads carry the station_code (ST-001) while
        # the session stores the DB primary key (st-001); resolve via the table.
        if event.get("station_id"):
            station = db.execute(
                select(Station).where(
                    or_(Station.station_code == event["station_id"], Station.id == event["station_id"])
                )
            ).scalar_one_or_none()
            if station is None or station.id != session.station_id:
                return self._reject(db, session, "station mismatch")

        if session.status in TERMINAL:
            raise DuplicateDepositError(
                f"operation {operation_id} already {session.status}"
            )

        expired = self._close_if_expired(db, session)
        if expired is not None:
            return expired

        claimed_status = event.get("status", CONFIRMED)
        actual_position = int(event.get("actual_position") or 0)
        weight = float(event.get("weight_grams") or 0.0)
        weight_stable = bool(event.get("weight_stable", False))
        beam_seen = bool(event.get("beam_event_seen", False))
        mechanical = bool(event.get("mechanical_confirmed", False))
        carriage_position = int(event.get("carriage_position") or 0)

        reason = self._physical_failure(
            session, claimed_status, actual_position, weight, weight_stable,
            beam_seen, mechanical, carriage_position,
        )
        if reason is not None:
            return self._reject(db, session, reason)

        try:
            event = award_points(
                db,
                session,
                actual_position=actual_position,
                weight_grams=weight,
                weight_stable=weight_stable,
                mechanical_confirmed=mechanical,
                points_awarded=session.potential_points,
            )
            # Challenge progress/completion rides the SAME transaction: the
            # reward is derived from this validated physical event and is
            # idempotent (unique user+challenge row). A crash here rolls back
            # base points AND bonus together.
            from .challenge_service import ChallengeService

            user = db.get(User, session.user_id)
            challenge_bonus = (
                ChallengeService().on_deposit_confirmed(db, user, event.predicted_class)
                if user is not None
                else 0
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("[POINTS] transaction failed operation=%s", operation_id)
            raise
        db.refresh(session)
        logger.info(
            "[VALIDATION] passed operation=%s", operation_id,
        )
        logger.info(
            "[POINTS] awarded=%s challenge_bonus=%s operation=%s",
            session.potential_points, challenge_bonus, operation_id,
        )
        result = _serialize(session)
        result["challenge_bonus"] = challenge_bonus
        return result

    # -- helpers -------------------------------------------------------------------

    def _close_if_expired(self, db: Session, session: DepositSession) -> dict | None:
        if _naive_utc(session.expires_at) < _naive_utc(_utcnow()):
            return self._reject(db, session, "deposit session expired", session_status=EXPIRED)
        return None

    def _reject(
        self,
        db: Session,
        session: DepositSession,
        reason: str,
        session_status: str = REJECTED,
    ) -> dict:
        if session.status not in TERMINAL:
            record_rejection(
                db, session,
                actual_position=session.actual_position,
                weight_grams=session.weight_grams,
                reason=reason,
                session_status=session_status,
            )
            db.commit()
            db.refresh(session)
        logger.info(
            "[VALIDATION] rejected operation=%s reason=%s", session.operation_id, reason,
        )
        return _serialize(session)

    def _physical_failure(
        self,
        session: DepositSession,
        claimed_status: str,
        actual_position: int,
        weight: float,
        weight_stable: bool,
        beam_seen: bool,
        mechanical: bool,
        carriage_position: int,
    ) -> str | None:
        if claimed_status != CONFIRMED:
            return _MACHINE_REASONS.get(claimed_status, "rejected by the machine")
        if actual_position != session.expected_position:
            return (
                f"wrong_position: expected compartment {session.expected_position}, "
                f"got {actual_position}"
            )
        if weight < settings.min_deposit_weight_grams:
            return (
                f"underweight: {weight:.2f}g below minimum "
                f"{settings.min_deposit_weight_grams}g"
            )
        if not weight_stable:
            return "weight not stable"
        if not beam_seen:
            return "no beam break detected"
        if not mechanical:
            return "no mechanical confirmation"
        if carriage_position != actual_position:
            return f"carriage not at deposit position ({carriage_position})"
        return None


def _serialize(session: DepositSession) -> dict:
    confirmed = session.status == CONFIRMED
    return {
        "operation_id": session.operation_id,
        "prediction_id": session.ai_prediction_id or "",
        "station_id": session.station_id,
        "predicted_class": session.expected_class or "",
        "expected_position": session.expected_position or 0,
        "confidence": session.confidence or 0.0,
        "confidence_level": session.confidence_level or "",
        "actual_position": session.actual_position or 0,
        "weight_g": round(session.weight_grams or 0.0, 2),
        "mechanical_confirmed": bool(session.mechanical_confirmed),
        "potential_points": session.potential_points,
        "points_awarded": session.potential_points if confirmed else 0,
        "status": session.status,
        "expires_at": _naive_utc(session.expires_at).isoformat(),
        "reject_reason": session.reject_reason,
    }
