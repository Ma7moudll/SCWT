from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import AuthToken, Faculty, User
from ..models.auth_token import hash_token
from ..repositories import UserRepository
from ..schemas import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    UserOut,
)
from ..security import create_access_token, get_current_user, hash_password, verify_password

from ..security.rate_limit import MemoryRateLimiter, client_identity
from ..security.revocation import revocations
from ..services.mailer import get_mailer

from pydantic import BaseModel, field_validator

class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.lower().strip()

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class VerifyEmailRequest(BaseModel):
    token: str


router = APIRouter(prefix="/auth", tags=["auth"])

# Sliding-window limiters (per process). Login is deliberately tight —
# brute force gets 5 attempts/minute/IP; register allows a lab room.
_login_limiter = MemoryRateLimiter(
    settings.auth_login_rate_limit, settings.auth_rate_window_seconds
)
_register_limiter = MemoryRateLimiter(
    settings.auth_register_rate_limit, settings.auth_rate_window_seconds
)
_forgot_limiter = MemoryRateLimiter(3, settings.auth_rate_window_seconds)
_reset_limiter = MemoryRateLimiter(5, settings.auth_rate_window_seconds)
_verify_limiter = MemoryRateLimiter(5, settings.auth_rate_window_seconds)


def faculty_name(db: Session, faculty_id: str) -> str:
    f = db.get(Faculty, faculty_id)
    return f.name if f else faculty_id


def payload_fields(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "studentCode": user.student_code,
        "name": user.name,
        "facultyId": user.faculty_id,
        "facultyName": faculty_name(db, user.faculty_id),
        "points": user.points,
        "avatarVersion": int(user.avatar_version or 0),
        # Exposed so the admin console can gate on role after sign-in.
        "role": user.role or "student",
    }


def _response(db: Session, user: User) -> AuthResponse:
    token = create_access_token(
        user.id, settings.jwt_secret, settings.jwt_access_token_minutes * 60,
        token_version=int(user.token_version or 0),
    )
    return AuthResponse(token=token, user=payload_fields(db, user))


def _issue_token(
    db: Session,
    user: User,
    purpose: str,
    ttl_seconds: int,
) -> str:
    """Creates a one-time token; only its hash is persisted."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    db.add(
        AuthToken(
            id=AuthToken.new_id(),
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
    )
    db.commit()
    return raw


def _consume_token(db: Session, raw_token: str, purpose: str) -> AuthToken | None:
    """Atomic single-use validation.

    Uses UPDATE ... WHERE used_at IS NULL to prevent double-use under concurrent
    requests (two simultaneous password-reset tab clicks cannot both succeed).
    """
    from sqlalchemy import update as sa_update

    hashed = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    # Read first to check expiry (non-exclusive; race is handled by the update).
    record = (
        db.query(AuthToken)
        .filter(
            AuthToken.token_hash == hashed,
            AuthToken.purpose == purpose,
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

    # Atomically mark as used; only ONE concurrent request can win this UPDATE.
    # The RETURNING row MUST be fetched before commit: SQLite cannot commit
    # while a statement is still open, and the row decides who won the race.
    result = db.execute(
        sa_update(AuthToken)
        .where(AuthToken.id == record.id, AuthToken.used_at.is_(None))
        .values(used_at=now)
        .returning(AuthToken.id)
    )
    winner = result.fetchone()
    db.commit()
    if winner is None:
        # Another request consumed the token between our SELECT and this UPDATE.
        return None
    db.refresh(record)
    return record


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> RegisterResponse:
    if not _register_limiter.hit(client_identity(request)):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a moment and try again.")
    repo = UserRepository()
    email = payload.email.lower().strip()
    if repo.get_by_email(db, email) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Please log in instead.")

    code = payload.studentCode or f"S-{email.split('@')[0][:6].upper()}"
    candidate = code
    suffix = 2
    while repo.get_by_student_code(db, candidate) is not None:
        candidate = f"{code}-{suffix}"
        suffix += 1

    faculty = db.get(Faculty, payload.facultyId)
    if faculty is None:
        raise HTTPException(status_code=422, detail="Please select a valid faculty.")

    user = User(
        email=email,
        student_code=candidate,
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        faculty_id=faculty.id,
        points=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Email verification: one-time token delivered via the configured mailer
    # (console in development). Delivery is a deployment concern.
    verification = _issue_token(
        db, user, "email_verification", settings.email_verification_token_ttl_seconds
    )
    get_mailer().send(
        to=email,
        subject="Verify your EcoLoop account",
        body=(
            f"Welcome to EcoLoop, {user.name}!\n\n"
            f"Verify your account: {settings.public_base_url}/verify-email?token={verification}\n"
            f"This link expires in {settings.email_verification_token_ttl_seconds // 3600} hours."
        ),
    )

    # Registration MUST NOT authenticate. No token is minted here; the
    # client must perform an explicit POST /auth/login to get a session.
    return RegisterResponse(user=payload_fields(db, user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> AuthResponse:
    if not _login_limiter.hit(client_identity(request)):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait a few minutes and try again.")
    user = UserRepository().get_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password. Please try again.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated. Please contact support.")
    if settings.email_verification_required and not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address before logging in. Check your inbox for the verification link.",
        )
    return _response(db, user)


@router.post("/logout")
def logout(
    request: Request,
    _user: User = Depends(get_current_user),
) -> dict:
    """Revokes the presented token's jti for its remaining lifetime."""
    import base64 as _b64, json as _json
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        # Token already validated by get_current_user; extract jti without
        # a second full HMAC round-trip by reading the already-verified payload.
        parts = token.split(".")
        payload = _json.loads(_b64.urlsafe_b64decode(parts[1] + "=="))
        jti = str(payload.get("jti", ""))
        remaining = float(payload.get("exp", 0)) - datetime.now(timezone.utc).timestamp()
        revocations.revoke(jti, max(remaining, 0.0))
    except Exception:
        pass  # token already validated; jti extraction failure is non-fatal
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    return UserOut(user=payload_fields(db, user))


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Always responds generically — no user enumeration.

    A real user receives a one-time reset link via the configured mailer;
    an unknown email silently does nothing."""
    if not _forgot_limiter.hit(client_identity(request)):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a moment and try again.")
    email = payload.email
    user = UserRepository().get_by_email(db, email) if email else None
    if user is not None and user.is_active:
        raw = _issue_token(
            db, user, "password_reset", settings.password_reset_token_ttl_seconds
        )
        get_mailer().send(
            to=email,
            subject="Reset your EcoLoop password",
            body=(
                f"Reset your password: {settings.public_base_url}/reset-password?token={raw}\n"
                f"This link expires in {settings.password_reset_token_ttl_seconds // 60} minutes "
                "and can be used once."
            ),
        )
    return {"status": "sent"}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Consumes a valid one-time reset token and sets the new password."""
    if not _reset_limiter.hit(client_identity(request)):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a moment and try again.")
    token = payload.token
    new_password = payload.new_password
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Your new password must be at least 8 characters long.")
    record = _consume_token(db, token, "password_reset")
    if record is None:
        raise HTTPException(status_code=422, detail="This password reset link is invalid or has expired. Please request a new one.")
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=422, detail="This password reset link is invalid or has expired. Please request a new one.")
    user.password_hash = hash_password(new_password)
    # Invalidate every outstanding session: tokens minted before this reset
    # carry an older `ver` and are refused from now on.
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return {"status": "password_reset"}


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Consumes a one-time verification token and marks the account verified."""
    if not _verify_limiter.hit(client_identity(request)):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a moment and try again.")
    token = payload.token
    record = _consume_token(db, token, "email_verification")
    if record is None:
        raise HTTPException(status_code=422, detail="This verification link is invalid or has expired. Please request a new one.")
    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(status_code=422, detail="This verification link is invalid or has expired. Please request a new one.")
    user.email_verified = True
    db.commit()
    return {"status": "verified"}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Logged-in password change.

    Requires the CURRENT password (step-up), enforces the same minimum length
    as reset-password, and invalidates EVERY outstanding access token for the
    account by bumping `token_version` — all previously issued JWTs carry the
    old version and are refused from that moment."""
    if not _reset_limiter.hit(client_identity(request)):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a moment and try again.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=422, detail="Your new password must be at least 8 characters long.")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Your current password is incorrect. Please try again.")
    user.password_hash = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return {"status": "password_changed"}
