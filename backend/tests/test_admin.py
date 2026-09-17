"""Admin surface (T23): every mutating admin route requires the admin role;
students get 403; admins manage stations/users/challenges."""
from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def _make_admin(email="admin@scwt.campus") -> None:
    with SessionLocal() as db:
        if db.query(User).filter(User.email == email).first() is None:
            db.add(
                User(
                    id="u-admin",
                    email=email,
                    student_code="S-ADMIN",
                    name="Admin",
                    password_hash=hash_password("admin-pass-123"),
                    faculty_id="ENGINEERING",
                    points=0,
                    role="admin",
                )
            )
            db.commit()


@pytest.fixture
def admin_auth(client):
    _make_admin()
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@scwt.campus", "password": "admin-pass-123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_student_cannot_create_station(client, auth):
    r = client.post(
        "/api/v1/admin/stations",
        headers=auth,
        json={"station_code": "ST-099", "name": "Sneaky Station"},
    )
    assert r.status_code == 403


def test_student_cannot_list_users(client, auth):
    assert client.get("/api/v1/admin/users", headers=auth).status_code == 403


def test_admin_can_create_and_patch_station(client, admin_auth):
    r = client.post(
        "/api/v1/admin/stations",
        headers=admin_auth,
        json={"station_code": "ST-002", "name": "Library Station"},
    )
    assert r.status_code == 200, r.text
    station = r.json()
    r = client.patch(
        f"/api/v1/admin/stations/{station['id']}",
        headers=admin_auth,
        json={"status": "online"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "online"


def test_admin_can_list_and_deactivate_user(client, admin_auth):
    users = client.get("/api/v1/admin/users", headers=admin_auth).json()["items"]
    assert any(u["email"] == "demo@scwt.campus" for u in users)

    target = next(u for u in users if u["email"] == "demo@scwt.campus")
    r = client.patch(
        f"/api/v1/admin/users/{target['id']}",
        headers=admin_auth,
        json={"is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # A deactivated user cannot log in.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "demo@scwt.campus", "password": "demo123"},
    )
    assert login.status_code == 403


def test_admin_cannot_deactivate_themselves(client, admin_auth):
    me = client.get("/api/v1/auth/me", headers=admin_auth).json()["user"]
    r = client.patch(
        f"/api/v1/admin/users/{me['id']}",
        headers=admin_auth,
        json={"is_active": False},
    )
    assert r.status_code in {400, 422}


def test_admin_can_create_challenge(client, admin_auth):
    r = client.post(
        "/api/v1/admin/challenges",
        headers=admin_auth,
        json={
            "title": "Metal Month",
            "description": "Deposit 5kg of metal",
            "waste_class": "metal",
            "target_kg": 5.0,
            "reward_points": 100,
        },
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------
# Dashboard / directory endpoints (regression: admin console data plane)
# --------------------------------------------------------------------------

def test_admin_overview_shape(client, admin_auth):
    r = client.get("/api/v1/admin/overview", headers=admin_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "total_students",
        "total_deposits",
        "recycled_kg",
        "points_awarded",
        "co2_saved_kg",
        "active_stations",
        "offline_stations",
        "today_activity",
    ):
        assert key in body
    assert body["total_students"] >= 1  # the seeded demo user


def test_admin_faculties_ranking(client, admin_auth):
    r = client.get("/api/v1/admin/faculties", headers=admin_auth)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "seeded faculties must be listed"
    ranks = [f["rank"] for f in items]
    assert ranks == sorted(ranks)
    names = {f["name"] for f in items}
    assert "Engineering" in names


def test_admin_stations_lists_seeded_station(client, admin_auth):
    r = client.get("/api/v1/admin/stations", headers=admin_auth)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(s["station_code"] == "ST-001" for s in items)


def test_admin_deposits_reflects_points(client, admin_auth, auth, plastic_prediction,
                                        monkeypatch):
    from tests.test_user_data import confirm_deposit

    confirm_deposit(client, auth, plastic_prediction)
    r = client.get("/api/v1/admin/deposits", headers=admin_auth)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "the confirmed deposit must appear"
    top = items[0]
    assert top["points"] > 0
    assert top["status"] == "confirmed"
    assert top["ai_class"] == "plastic"


def test_admin_users_search_filter_and_paging(client, admin_auth):
    # Two more students in different faculties.
    client.post("/api/v1/auth/register", json={
        "name": "Zara Physical", "email": "zara@uni.edu",
        "facultyId": "PHYSICAL_THERAPY", "password": "secret99"})
    client.post("/api/v1/auth/register", json={
        "name": "Yusuf Art", "email": "yusuf@uni.edu",
        "facultyId": "ART_DESIGN", "password": "secret99"})

    r = client.get("/api/v1/admin/users?q=zara", headers=admin_auth)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["email"] == "zara@uni.edu"

    r = client.get("/api/v1/admin/users?faculty=PHYSICAL_THERAPY", headers=admin_auth)
    items = r.json()["items"]
    assert items and all(u["faculty_id"] == "PHYSICAL_THERAPY" for u in items)

    r = client.get("/api/v1/admin/users?limit=2&offset=0", headers=admin_auth)
    body = r.json()
    assert len(body["items"]) <= 2 and body["total"] >= 3

    # Student codes and faculty display names are exposed for the directory.
    r = client.get("/api/v1/admin/users?q=demo@scwt.campus", headers=admin_auth)
    demo = r.json()["items"][0]
    assert demo["student_code"]
    assert demo["faculty_name"] == "Engineering"


def test_admin_console_shell_public_data_gated(client, auth, admin_auth):
    # The HTML shell is inert and reachable without a token…
    shell = client.get("/api/v1/admin/ui")
    assert shell.status_code == 200
    assert "SCWT Admin" in shell.text
    assert "demo@scwt.campus" not in shell.text
    # …but every DATA endpoint is locked down.
    assert client.get("/api/v1/admin/overview").status_code == 401
    assert client.get("/api/v1/admin/overview", headers=auth).status_code == 403
    assert client.get("/api/v1/admin/deposits", headers=auth).status_code == 403


# --------------------------------------------------------------------------
# CRUD extensions (regression: admin console add/edit/delete surface)
# --------------------------------------------------------------------------


def test_admin_station_rename_and_delete_cycle(client, admin_auth):
    r = client.post(
        "/api/v1/admin/stations",
        headers=admin_auth,
        json={"station_code": "ST-CRUD", "name": "CRUD Station"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    r = client.patch(
        f"/api/v1/admin/stations/{sid}", headers=admin_auth,
        json={"name": "CRUD Renamed"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "CRUD Renamed"

    r = client.delete(f"/api/v1/admin/stations/{sid}", headers=admin_auth)
    assert r.status_code == 200
    assert r.json()["deleted"] == sid

    items = client.get("/api/v1/admin/stations", headers=admin_auth).json()["items"]
    assert all(s["id"] != sid for s in items)


def test_admin_cannot_delete_station_with_deposit_history(
    client, admin_auth, auth, plastic_prediction
):
    from .test_user_data import confirm_deposit

    confirm_deposit(client, auth, plastic_prediction)  # lands on st-001
    r = client.delete("/api/v1/admin/stations/st-001", headers=admin_auth)
    assert r.status_code == 409


def test_admin_patch_user_fields_and_self_guards(client, admin_auth):
    from .conftest import register_and_login

    register_and_login(client, "crud-patch@uni.edu")
    users = client.get(
        "/api/v1/admin/users?q=crud-patch", headers=admin_auth
    ).json()["items"]
    uid = users[0]["id"]

    r = client.patch(
        f"/api/v1/admin/users/{uid}", headers=admin_auth,
        json={"points": 42, "name": "Renamed Student"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == 42 and body["name"] == "Renamed Student"

    # invalid role rejected outright
    r = client.patch(
        f"/api/v1/admin/users/{uid}", headers=admin_auth,
        json={"role": "superadmin"},
    )
    assert r.status_code == 422

    me = client.get("/api/v1/auth/me", headers=admin_auth).json()["user"]
    r = client.patch(
        f"/api/v1/admin/users/{me['id']}", headers=admin_auth,
        json={"role": "student"},
    )
    assert r.status_code in {400, 422}


def test_admin_delete_user_history_guard_and_success(
    client, admin_auth, auth, plastic_prediction
):
    from .conftest import register_and_login
    from .test_user_data import confirm_deposit

    # give demo a deposit -> must NOT hard-delete
    confirm_deposit(client, auth, plastic_prediction)
    demo = next(
        u for u in client.get("/api/v1/admin/users", headers=admin_auth).json()["items"]
        if u["email"] == "demo@scwt.campus"
    )
    r = client.delete(f"/api/v1/admin/users/{demo['id']}", headers=admin_auth)
    assert r.status_code == 409

    # fresh account without history -> hard delete succeeds
    register_and_login(client, "crud-del@uni.edu")
    users = client.get(
        "/api/v1/admin/users?q=crud-del", headers=admin_auth
    ).json()["items"]
    uid = users[0]["id"]
    r = client.delete(f"/api/v1/admin/users/{uid}", headers=admin_auth)
    assert r.status_code == 200
    leftovers = client.get(
        "/api/v1/admin/users?q=crud-del", headers=admin_auth
    ).json()["items"]
    assert all(u["id"] != uid for u in leftovers)


def test_admin_challenge_full_crud_cycle(client, admin_auth):
    r = client.post(
        "/api/v1/admin/challenges", headers=admin_auth,
        json={
            "title": "CRUD Cycle", "description": "tmp",
            "theme_emoji": "♻️", "waste_class": "plastic",
            "target_kg": 1.5, "reward_points": 10,
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    r = client.patch(
        f"/api/v1/admin/challenges/{cid}", headers=admin_auth,
        json={"title": "CRUD Renamed", "target_kg": 2.0},
    )
    assert r.status_code == 200

    listed = client.get("/api/v1/admin/challenges", headers=admin_auth).json()["items"]
    row = next(c for c in listed if c["id"] == cid)
    assert row["title"] == "CRUD Renamed" and float(row["target_kg"]) == 2.0

    r = client.delete(f"/api/v1/admin/challenges/{cid}", headers=admin_auth)
    assert r.status_code == 200
    ids = [
        c["id"] for c in client.get("/api/v1/admin/challenges", headers=admin_auth).json()["items"]
    ]
    assert cid not in ids


def test_admin_cannot_delete_joined_challenge(
    client, admin_auth, auth, plastic_prediction
):
    """A deposit crossing a tiny target auto-completes the challenge, creating
    a UserChallenge row; challenges with joiners are undeletable."""
    from .test_user_data import confirm_deposit

    r = client.post(
        "/api/v1/admin/challenges", headers=admin_auth,
        json={
            "title": "Sticky Challenge", "description": "cannot delete",
            "theme_emoji": "🧲", "waste_class": "plastic",
            "target_kg": 0.001, "reward_points": 5,
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    confirm_deposit(client, auth, plastic_prediction)  # creates the joiner

    r = client.delete(f"/api/v1/admin/challenges/{cid}", headers=admin_auth)
    assert r.status_code == 409


def test_faculty_crud_lifecycle(client, admin_auth):
    # create -> slug id, listed
    r = client.post(
        "/api/v1/admin/faculties", headers=admin_auth,
        json={"name": "Marine Biology"},
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert fid == "MARINE_BIOLOGY"

    # duplicate name refused
    assert client.post(
        "/api/v1/admin/faculties", headers=admin_auth,
        json={"name": "Marine Biology"},
    ).status_code == 409

    # rename updates the faculty AND its leaderboard row name
    assert client.patch(
        f"/api/v1/admin/faculties/{fid}", headers=admin_auth,
        json={"name": "Marine Sciences"},
    ).status_code == 200
    names = [f["name"] for f in client.get(
        "/api/v1/admin/faculties", headers=admin_auth).json()["items"]]
    assert "Marine Sciences" in names

    # delete empty faculty works; deleting one with students is refused
    from .conftest import register_and_login

    register_and_login(client, "faculty-guard@uni.edu")  # ENGINEERING by default
    assert client.delete(
        "/api/v1/admin/faculties/ENGINEERING", headers=admin_auth
    ).status_code == 409

    assert client.delete(f"/api/v1/admin/faculties/{fid}", headers=admin_auth).status_code == 200
    ids = [f["id"] for f in client.get(
        "/api/v1/admin/faculties", headers=admin_auth).json()["items"]]
    assert fid not in ids

    # student/anonymous are locked out
    assert client.get("/api/v1/admin/faculties").status_code == 401
