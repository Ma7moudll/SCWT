"""User-data endpoints: /users/me, waste history, impact, leaderboard,
challenges — matching the Flutter data-repository contract."""
from __future__ import annotations

from .conftest import confirm_event


def confirm_deposit(client, auth, prediction, **kwargs) -> dict:
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": prediction["prediction_id"], "station_id": "st-001"},
    )
    assert r.status_code == 200, r.text
    session = r.json()
    r = client.post(
        "/api/v1/deposit/callback/event",
        headers={"X-Station-Key": "ecolamp-dev-station-key"},
        json=confirm_event(session["operation_id"], **kwargs),
    )
    assert r.status_code == 200, r.text
    return session


def test_impact_after_one_deposit(client, auth, plastic_prediction):
    confirm_deposit(client, auth, plastic_prediction,
                    position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    r = client.get("/api/v1/impact", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["items_recycled"] == 1
    assert body["total_points"] == 50  # 45 seeded + 5 awarded
    assert body["recycled_kg"] > 0
    by_class = {c["waste_class"]: c for c in body["breakdown"]}
    assert by_class["plastic"]["count"] == 1


def test_waste_history_lists_audit_trail(client, auth, plastic_prediction):
    session = confirm_deposit(client, auth, plastic_prediction,
                              position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    r = client.get("/api/v1/waste/history", headers=auth)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["operation_id"] == session["operation_id"] for i in items)
    recovered = [i for i in items if i["operation_id"] == session["operation_id"]][0]
    assert recovered["predicted_class"] == "plastic"
    assert recovered["points_awarded"] == 5


def test_rejected_deposit_still_in_history_with_zero_points(client, auth, plastic_prediction):
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": plastic_prediction["prediction_id"], "station_id": "st-001"},
    )
    session = r.json()
    client.post("/api/v1/deposit/callback/event",
                headers={"X-Station-Key": "ecolamp-dev-station-key"},
                json=confirm_event(session["operation_id"], position=2, weight=18.4,
                                   stable=True, beam=True, mech=True, carriage=2))
    r = client.get("/api/v1/waste/history", headers=auth)
    items = r.json()["items"]
    ev = [i for i in items if i["operation_id"] == session["operation_id"]][0]
    assert ev["points_awarded"] == 0  # rejected: audited but zero points


def test_leaderboard_aggregates_students_and_faculties(client, auth, plastic_prediction):
    confirm_deposit(client, auth, plastic_prediction,
                    position=1, weight=18.4, stable=True, beam=True, mech=True, carriage=1)
    r = client.get("/api/v1/leaderboard?scope=students", headers=auth)
    entries = r.json()["entries"]
    top = entries[0]
    assert top["name"] == "Demo Student"
    assert top["points"] == 50  # 45 seeded + 5
    assert top["id"]  # Flutter LeaderEntry.id
    rf = client.get("/api/v1/leaderboard/faculties", headers=auth)
    fac = [e for e in rf.json()["entries"] if e["id"] == "ENGINEERING"][0]
    assert fac["points"] == 50


def test_challenges_endpoint(client, auth):
    r = client.get("/api/v1/challenges", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


def test_users_me_returns_user_wrapper(client, auth):
    r = client.get("/api/v1/users/me", headers=auth)
    assert r.status_code == 200
    assert "user" in r.json()

# --------------------------------------------------------------------------
# Profile edit + password change (regression: account self-service)
# --------------------------------------------------------------------------

def test_update_profile_name_and_faculty(client, auth):
    r = client.patch(
        "/api/v1/users/me/profile",
        headers=auth,
        json={"name": "Demo Renamed", "faculty_id": "ART_DESIGN"},
    )
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["name"] == "Demo Renamed"
    assert user["facultyId"] == "ART_DESIGN"

    # /auth/me reflects the change too.
    me = client.get("/api/v1/auth/me", headers=auth).json()["user"]
    assert me["name"] == "Demo Renamed"


def test_update_profile_rejects_unknown_faculty_and_empty(client, auth):
    r = client.patch("/api/v1/users/me/profile", headers=auth,
                     json={"faculty_id": "nope"})
    assert r.status_code == 422
    r = client.patch("/api/v1/users/me/profile", headers=auth, json={})
    assert r.status_code == 422
    r = client.patch("/api/v1/users/me/profile", headers=auth, json={"name": "  "})
    assert r.status_code == 422


def test_change_password_invalidates_outstanding_tokens(client):
    login = client.post("/api/v1/auth/login",
                        json={"email": "demo@ecolamp.campus", "password": "demo123"})
    old_token = login.json()["token"]
    old_auth = {"Authorization": f"Bearer {old_token}"}

    # Wrong current password refused.
    r = client.post("/api/v1/auth/change-password", headers=old_auth,
                    json={"current_password": "wrong-pass", "new_password": "new-pass-123"})
    assert r.status_code == 401

    # Correct change succeeds…
    r = client.post("/api/v1/auth/change-password", headers=old_auth,
                    json={"current_password": "demo123", "new_password": "new-pass-123"})
    assert r.status_code == 200

    # …and EVERY previously issued token is now dead (401 on /auth/me).
    assert client.get("/api/v1/auth/me", headers=old_auth).status_code == 401

    # Login works with the new password only.
    assert client.post("/api/v1/auth/login",
                       json={"email": "demo@ecolamp.campus", "password": "demo123"}).status_code == 401
    relogin = client.post("/api/v1/auth/login",
                          json={"email": "demo@ecolamp.campus", "password": "new-pass-123"})
    assert relogin.status_code == 200


# --------------------------------------------------------------------------
# Profile avatar (upload / fetch / remove)
# --------------------------------------------------------------------------

import io


def _jpeg_bytes() -> bytes:
    # Minimal valid JPEG (SOI + JFIF-APP0 header); magic bytes are what the
    # endpoint validates.
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _upload(client, auth, data: bytes, filename="me.jpg", kind="image/jpeg"):
    return client.put(
        "/api/v1/users/me/avatar",
        headers=auth,
        files={"file": (filename, io.BytesIO(data), kind)},
    )


def test_avatar_upload_fetch_and_version(client, auth):
    me = client.get("/api/v1/auth/me", headers=auth).json()["user"]
    assert me["avatarVersion"] == 0

    r = _upload(client, auth, _jpeg_bytes())
    assert r.status_code == 200, r.text
    assert r.json()["user"]["avatarVersion"] == 1

    # Second upload bumps again (cache busting).
    r = _upload(client, auth, _png_bytes(), filename="me.png", kind="image/png")
    assert r.json()["user"]["avatarVersion"] == 2

    fetched = client.get(f"/api/v1/users/avatar/{me['id']}?v=2")
    assert fetched.status_code == 200
    assert fetched.content == _png_bytes()


def test_avatar_rejects_non_image_and_oversize(client, auth):
    r = _upload(client, auth, b"definitely not an image", kind="image/jpeg")
    assert r.status_code == 422
    assert "image" in r.json()["error"].lower()

    big = _jpeg_bytes() + b"\x00" * (3 * 1024 * 1024)
    r = _upload(client, auth, big)
    assert r.status_code == 413


def test_avatar_remove(client, auth):
    me = client.get("/api/v1/auth/me", headers=auth).json()["user"]
    _upload(client, auth, _jpeg_bytes())
    r = client.delete("/api/v1/users/me/avatar", headers=auth)
    assert r.status_code == 200
    assert r.json()["user"]["avatarVersion"] == 0
    assert client.get(f"/api/v1/users/avatar/{me['id']}").status_code == 404


def test_avatar_requires_auth(client):
    r = client.put(
        "/api/v1/users/me/avatar",
        files={"file": ("x.jpg", io.BytesIO(_jpeg_bytes()), "image/jpeg")},
    )
    assert r.status_code == 401
