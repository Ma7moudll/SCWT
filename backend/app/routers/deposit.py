from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..models.auth_token import hash_token
from ..mqtt import RuntimePublisher
from ..schemas import (
    CallbackEvent,
    ClaimSessionRequest,
    CreateSessionRequest,
    HandoffTokenResponse,
)
from ..security import get_current_user
from ..services import DepositService
from ..services.ai_client import AiGateRejection, AiWireError
from ..services.deposit_service import DepositEventError, DuplicateDepositError

logger = logging.getLogger("recycle.deposit")

router = APIRouter(prefix="/deposit", tags=["deposit"])

_publisher = RuntimePublisher()


@router.post("/handoff-token", response_model=HandoffTokenResponse)
def handoff_token(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HandoffTokenResponse:
    """Mints the student's short-lived deposit-handoff QR token.

    The Ecolamp app renders `{token}` as a QR; the STATION tablet scans it and
    exchanges it (authenticated with its station key) via
    `POST /deposit/session/claim`. Single-use + short TTL => a scanned or
    shoulder-surfed QR cannot be replayed, and no long-lived secret ever
    enters the QR payload."""
    from datetime import datetime, timedelta, timezone

    from ..models.auth_token import AuthToken

    ttl = settings.deposit_handoff_token_ttl_seconds
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    db.add(
        AuthToken(
            id=AuthToken.new_id(),
            user_id=user.id,
            purpose="deposit_handoff",
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )
    )
    db.commit()
    return HandoffTokenResponse(
        token=raw,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
    )


@router.post("/session/claim")
def claim_session(
    payload: ClaimSessionRequest,
    x_station_key: str = Header(default="", alias="X-Station-Key"),
    db: Session = Depends(get_db),
) -> dict:
    """Station-side claim of a student handoff QR (Ecolamp flow).

    The station tablet — authenticated with `X-Station-Key`, the same trust
    boundary as `/deposit/capture` — consumes the student's single-use
    handoff token and creates a capture-first deposit session for that
    student at this station. Atomically single-use: two concurrent scans of
    the same QR cannot both succeed. Points are impossible here; only a
    physical MQTT `deposit_result` can complete the deposit."""
    if not x_station_key or x_station_key != settings.station_api_key:
        return JSONResponse(status_code=401, content={"error": "Invalid station key"})

    auth_token_record = _consume_handoff_token(db, payload.token)
    if auth_token_record is None:
        return JSONResponse(
            status_code=422,
            content={"code": "INVALID_HANDOFF_TOKEN",
                     "error": "This QR code is invalid or has expired. Ask the student to refresh it."},
        )

    user = db.get(User, auth_token_record.user_id)
    if user is None:
        return JSONResponse(
            status_code=422,
            content={"code": "INVALID_HANDOFF_TOKEN", "error": "Unknown student account."},
        )
    try:
        session = DepositService(_publisher).create_session(
            db, user, prediction_id=None, station_id=payload.station_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _wire_session(session)


def _consume_handoff_token(db: Session, raw_token: str):
    """Atomic single-use consumption of a deposit_handoff token."""
    from datetime import datetime, timezone

    from sqlalchemy import update as sa_update

    from ..models.auth_token import AuthToken, hash_token

    hashed = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    record = (
        db.query(AuthToken)
        .filter(
            AuthToken.token_hash == hashed,
            AuthToken.purpose == "deposit_handoff",
            AuthToken.used_at.is_(None),
        )
        .first()
    )
    if record is None:
        return None
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        return None
    result = db.execute(
        sa_update(AuthToken)
        .where(AuthToken.id == record.id, AuthToken.used_at.is_(None))
        .values(used_at=now)
        .returning(AuthToken.id)
    )
    winner = result.fetchone()
    db.commit()
    if winner is None:
        return None
    db.refresh(record)
    return record


@router.post("/session")
def create_session(
    payload: CreateSessionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Creates a tracked deposit session.

    With `ai_prediction_id` (legacy phone-camera path) the MQTT routing command
    is issued immediately. Without one (FINAL station-camera path) the session
    is created capture-first and a `capture_request` command tells the station
    camera to snap the frame; `POST /deposit/capture` then classifies and
    routes. Awarding points is impossible here — only physical MQTT sensor
    events can complete a deposit."""
    try:
        session = DepositService(_publisher).create_session(
            db,
            user,
            prediction_id=payload.ai_prediction_id,
            station_id=payload.station_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _wire_session(session)


@router.post("/capture")
def capture(
    image: UploadFile = File(...),
    operation_id: str = Form(...),
    station_code: str = Form(...),
    x_station_key: str = Header(default="", alias="X-Station-Key"),
    db: Session = Depends(get_db),
) -> dict:
    """Station-camera capture endpoint (FINAL architecture).

    The STATION camera — not the phone — is the classification source. The
    backend runs the real `PredictService`, attaches the prediction to the
    session and auto-routes per the confidence policy (HIGH auto / MEDIUM
    manual / LOW rejected). A rejected frame from the AI input gate returns a
    structured 422 so the camera can retake. Points still require the physical
    MQTT `deposit_result` event — this endpoint can never award points."""
    if not x_station_key or x_station_key != settings.station_api_key:
        return JSONResponse(status_code=401, content={"error": "Invalid station key"})

    # Reject oversized uploads BEFORE reading/expensive processing. Prefer the
    # declared Content-Length when present, then enforce the hard cap while
    # streaming so a lying header cannot bypass the limit.
    declared = image.size
    if declared is not None and declared > settings.max_upload_bytes:
        return JSONResponse(status_code=413, content={"error": "payload_too_large"})
    image_bytes = image.file.read(settings.max_upload_bytes + 1)
    if len(image_bytes) > settings.max_upload_bytes:
        return JSONResponse(status_code=413, content={"error": "payload_too_large"})
    if not image_bytes:
        raise HTTPException(status_code=422, detail="The captured image is empty. Please try again.")
    try:
        return DepositService(_publisher).handle_capture(
            db, operation_id, station_code, image_bytes,
            image_url=f"station-camera://{station_code}",
        )
    except AiGateRejection as exc:
        return JSONResponse(status_code=422, content={"code": exc.code, "error": exc.detail})
    except AiWireError as exc:
        # AI service unreachable/errored: the session was reverted to `capture`
        # so the camera can retake; surface a structured 503 (not a 500 leak).
        return JSONResponse(status_code=503, content={"code": "AI_UNAVAILABLE", "error": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/active")
def active_deposit(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """The caller's current NON-TERMINAL deposit session, if any.

    Used by the student app after a station claims its handoff QR: the phone
    does not receive the claim response, so it polls here until the session
    created by `POST /deposit/session/claim` shows up."""
    from sqlalchemy import select

    from ..models import DepositSession
    from ..services.deposit_service import TERMINAL

    row = (
        db.execute(
            select(DepositSession)
            .where(
                DepositSession.user_id == user.id,
                DepositSession.status.notin_(TERMINAL),
            )
            .order_by(DepositSession.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if row is None:
        return JSONResponse(status_code=404, content={"error": "No active deposit."})
    return {"deposit": _wire_session(row)}


@router.get("/{operation_id}")
def get_deposit(
    operation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from ..repositories import DepositRepository

    session = DepositRepository().get_by_operation_id(db, operation_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="This deposit could not be found.")
    return _wire_session(session)


@router.post("/{operation_id}/cancel")
def cancel(
    operation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        session = DepositService(_publisher).cancel(db, user, operation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _wire_session(session)


@router.post("/callback/event")
def callback(
    event: CallbackEvent,
    x_station_key: str = Header(default="", alias="X-Station-Key"),
    db: Session = Depends(get_db),
) -> dict:
    """HTTP parity path for hardware events (used when a MQTT bridge is not
    available). The normal path is MQTT directly (broker-internal trust
    boundary); this HTTP path is internet-reachable and REQUIRES the same
    `X-Station-Key` as the capture endpoint so a random caller cannot fabricate
    a `deposit_result` event and award themselves points. Both invoke the exact
    same validation pipeline and can never award points without a valid
    physics event."""
    if not x_station_key or x_station_key != settings.station_api_key:
        return JSONResponse(status_code=401, content={"error": "Invalid station key"})
    try:
        result = DepositService(_publisher).complete_from_event(db, event.model_dump())
    except DuplicateDepositError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DepositEventError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


def _wire_session(session) -> dict:
    from ..services.deposit_service import _naive_utc

    confirmed = session.status == "confirmed"
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