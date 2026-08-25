"""Debug-only byte-identity router: mounted only when DEBUG_IMAGE_HASH=true.

The hardware validation harness uses this fingerprint route to prove that the
exact bytes the STATION camera captured arrive at the backend unchanged (by
comparing the SHA-256 computed on-device against the hash of what the HTTP
layer received). It must NOT exist in a normal build.
"""
from __future__ import annotations

import hashlib

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.routers import debug_router
from app.security import get_current_user


def test_debug_route_not_mounted_by_default(client):
    """Normal builds never expose the hash-echo route (DEBUG_IMAGE_HASH=false)."""
    r = client.post(
        "/api/v1/debug/image-sha256",
        headers={"Authorization": "Bearer whatever"},
        files={"image": ("junk.png", b"junk", "image/png")},
    )
    assert r.status_code == 404


def test_debug_route_echoes_the_exact_captured_bytes():
    """With the debug router mounted, the route returns the SHA-256 of the
    exact bytes received — the on-device camera hash must equal this value."""

    async def _fake_current_user():
        return object()

    app = FastAPI(title="debug-only")
    app.include_router(debug_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _fake_current_user

    client = TestClient(app)
    payload = b"\xff\xd8\xff\xe0\x00\x10JFIF fake-capture-jpeg"
    r = client.post(
        "/api/v1/debug/image-sha256",
        headers={"Authorization": "Bearer tok"},
        files={"image": ("cap.jpg", payload, "image/jpeg")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sha256"] == hashlib.sha256(payload).hexdigest()
    assert body["size"] == len(payload)