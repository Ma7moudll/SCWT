from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

WasteClass = Any  # 'plastic' | 'metal' | 'paper' | 'other'


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: str
    studentCode: str | None = Field(default=None, max_length=64)
    facultyId: str = Field(...)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict[str, Any]


class RegisterResponse(BaseModel):
    """Account-creation response — deliberately NOT an AuthResponse.

    Registration must never authenticate: no token is minted, and the client
    must send the user through /auth/login to establish a session."""

    user: dict[str, Any]


class UserOut(BaseModel):
    user: dict[str, Any]


class PredictionResponse(BaseModel):
    prediction_id: str
    operation_id: str
    predicted_class: str
    confidence: float
    confidence_level: str
    recyclable: bool
    destination_position: int
    potential_points: int
    expires_at: datetime
    source: str


class CreateSessionRequest(BaseModel):
    """Station-session identification. `ai_prediction_id` is OPTIONAL: with a
    prediction present this is the legacy phone-camera path; without one the
    session is created capture-first and the STATION camera supplies the frame
    via the station-key-authenticated capture endpoint."""

    ai_prediction_id: str | None = None
    station_id: str = "st-001"


class CaptureRejectionResponse(BaseModel):
    """Structured 422 body returned by `POST /deposit/capture` when the frame
    cannot yield a routable prediction (gate rejection or low confidence)."""

    code: str
    error: str


class CancelRequest(BaseModel):
    operation_id: str


class HandoffTokenResponse(BaseModel):
    """Short-lived single-use token the student app renders as a QR code.

    The station tablet scans it and exchanges it (with its station key) via
    `POST /deposit/session/claim`. The raw token is never stored server-side
    (only its hash) and can be consumed exactly once."""

    token: str
    expires_at: datetime


class ClaimSessionRequest(BaseModel):
    """Station -> backend claim of a student handoff QR.

    Requires the `X-Station-Key` header; creates a capture-first deposit
    session for the student encoded in the single-use token."""

    token: str = Field(min_length=16, max_length=128)
    station_id: str = "st-001"


class DepositCreatedResponse(BaseModel):
    deposit: dict[str, Any]


class DepositConfirmRequest(BaseModel):
    """Accepted for API continuity ONLY when running the legacy simulator
    bridge. Real deposits are completed exclusively via MQTT sensor events."""

    operation_id: str
    actual_position: int
    weight_g: float
    mechanical_confirmed: bool = True


class CallbackEvent(BaseModel):
    """Terminal physical deposit event — the MQTT `deposit_result` payload.
    Used by the HTTP callback parity path and by MQTT message decoding."""

    station_id: str
    operation_id: str
    event: str = "deposit_result"
    status: str = "confirmed"
    actual_position: int = 0
    carriage_position: int = 0
    weight_grams: float = 0.0
    weight_stable: bool = False
    beam_event_seen: bool = False
    mechanical_confirmed: bool = False
    reason: str | None = None