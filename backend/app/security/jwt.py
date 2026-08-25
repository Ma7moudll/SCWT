"""Stateless HS256 JWT mint/verify."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: bytes, secret: str) -> str:
    h = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64(h)


def create_access_token(user_id: str, secret: str, ttl_seconds: int, token_version: int = 0) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    body = {
        "sub": user_id,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": str(uuid.uuid4()),
        # Token generation: bumped on password change/reset so every token
        # issued before the credential change is refused from that moment.
        "ver": int(token_version),
    }
    h = _b64(json.dumps(header, separators=(",", ":")).encode())
    b = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{h}.{b}.{_sign(f'{h}.{b}'.encode(), secret)}"


def decode_access_token(token: str, secret: str) -> dict:
    """Raises ValueError for any malformed / expired / tampered token."""
    header, body, sig = token.split(".")
    if not hmac.compare_digest(sig.encode(), _sign(f"{header}.{body}".encode(), secret).encode()):
        raise ValueError("invalid signature")
    payload = json.loads(_unb64(body))
    if payload.get("exp", 0) < time.time():
        raise ValueError("token expired")
    if not payload.get("sub"):
        raise ValueError("missing subject")
    return payload