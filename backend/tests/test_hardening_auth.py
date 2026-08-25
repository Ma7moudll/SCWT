"""Hardening tests for the auth surface (T11/T12/T13/T14/T15):

* login/register rate limiting -> 429
* logout revokes the presented token's jti
* forgot-password never enumerates users; reset-password consumes a one-time
  hashed token; short passwords rejected
* verify-email marks the account verified

The mailer is replaced with a recording fake so tests can read one-time
tokens without depending on log output.
"""
from __future__ import annotations

from app.database import SessionLocal
from app.models import User

from .conftest import DEMO_EMAIL, DEMO_PASSWORD


class RecordingMailer:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.messages.append({"to": to, "subject": subject, "body": body})


def _install_mailer(monkeypatch) -> RecordingMailer:
    from app.routers import auth as auth_router

    fake = RecordingMailer()
    monkeypatch.setattr(auth_router, "get_mailer", lambda: fake)
    return fake


def _login(client):
    return client.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

def test_login_rate_limited_after_limit(client, monkeypatch):
    # fresh_db resets the limiters; settings default is 5/min.
    codes = []
    for _ in range(7):
        r = _login(client)
        codes.append(r.status_code)
    assert codes[:5] == [200] * 5
    assert codes[5] == 429 and codes[6] == 429


def test_wrong_password_counts_against_rate_limit(client):
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": DEMO_EMAIL, "password": "wrong-password"},
        )
    r = _login(client)  # correct credentials still blocked once over budget
    assert r.status_code == 429


def test_register_rate_limited(client, monkeypatch):
    _install_mailer(monkeypatch)
    payload = {
        "email": "ratelimit@recycle.vision",
        "password": "password123",
        "name": "RL",
        "facultyId": "ENGINEERING",
    }
    codes = []
    for i in range(12):
        p = dict(payload, email=f"ratelimit{i}@recycle.vision")
        codes.append(client.post("/api/v1/auth/register", json=p).status_code)
    assert codes.count(429) >= 1


# --------------------------------------------------------------------------
# Logout revocation
# --------------------------------------------------------------------------

def test_logout_revokes_token(client):
    token = _login(client).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 200

    r = client.post("/api/v1/auth/logout", headers=auth)
    assert r.status_code == 200

    # The same token is now rejected everywhere get_current_user guards.
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401


def test_other_token_still_valid_after_logout(client):
    first = _login(client).json()["token"]
    second = _login(client).json()["token"]
    client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {first}"}
    )
    # Only the logged-out jti is revoked — the independent session survives.
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second}"})
    assert r.status_code == 200


# --------------------------------------------------------------------------
# Password reset (no enumeration + one-time token)
# --------------------------------------------------------------------------

def test_forgot_password_never_enumerates(client, monkeypatch):
    mailer = _install_mailer(monkeypatch)
    known = client.post(
        "/api/v1/auth/forgot-password", json={"email": DEMO_EMAIL}
    )
    unknown = client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@recycle.vision"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    # Exactly ONE email went out — only to the real account.
    assert len(mailer.messages) == 1
    assert mailer.messages[0]["to"] == DEMO_EMAIL


def test_reset_password_full_flow(client, monkeypatch):
    mailer = _install_mailer(monkeypatch)
    client.post("/api/v1/auth/forgot-password", json={"email": DEMO_EMAIL})
    token = mailer.messages[0]["body"].split("token=")[1].split("\n")[0]

    new_password = "brand-new-pass-9"
    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": new_password},
    )
    assert r.status_code == 200

    # Old password no longer works; new one does.
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": new_password}
        ).status_code
        == 200
    )


def test_reset_password_token_is_single_use(client, monkeypatch):
    mailer = _install_mailer(monkeypatch)
    client.post("/api/v1/auth/forgot-password", json={"email": DEMO_EMAIL})
    token = mailer.messages[0]["body"].split("token=")[1].split("\n")[0]
    payload = {"token": token, "new_password": "reuse-attempt-1"}
    assert (
        client.post("/api/v1/auth/reset-password", json=payload).status_code == 200
    )
    payload["new_password"] = "reuse-attempt-2"
    assert (
        client.post("/api/v1/auth/reset-password", json=payload).status_code == 422
    )


def test_reset_password_rejects_short_password(client, monkeypatch):
    mailer = _install_mailer(monkeypatch)
    client.post("/api/v1/auth/forgot-password", json={"email": DEMO_EMAIL})
    token = mailer.messages[0]["body"].split("token=")[1].split("\n")[0]
    r = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert r.status_code == 422
    # The token was NOT consumed by the failed attempt.
    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "valid-password-1"},
    )
    assert r.status_code == 200


def test_reset_password_rejects_garbage_token(client):
    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "whatever-123"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------

def test_registration_sends_verification_and_verify_email_works(
    client, monkeypatch
):
    mailer = _install_mailer(monkeypatch)
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "verify@recycle.vision",
            "password": "password123",
            "name": "Verify Me",
            "facultyId": "ENGINEERING",
        },
    )
    assert r.status_code == 201
    verification = next(
        m for m in mailer.messages if "Verify" in m["subject"]
    )
    token = verification["body"].split("token=")[1].split("\n")[0]

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "verify@recycle.vision").first()
        assert user.email_verified is False

    r = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 200

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "verify@recycle.vision").first()
        assert user.email_verified is True


def test_verify_email_token_is_single_use(client, monkeypatch):
    mailer = _install_mailer(monkeypatch)
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "verify-once@recycle.vision",
            "password": "password123",
            "name": "Once",
            "facultyId": "ENGINEERING",
        },
    )
    token = next(
        m for m in mailer.messages if "Verify" in m["subject"]
    )["body"].split("token=")[1].split("\n")[0]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 422
