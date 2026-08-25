"""Auth contract tests (mirror the Flutter ApiClient)."""
from __future__ import annotations

import re

from .conftest import DEMO_EMAIL, DEMO_PASSWORD


def test_register_new_user(client):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Ada Lovelace",
            "email": "ada@uni.edu",
            "studentCode": "S-ADA1",
            "facultyId": "ENGINEERING",
            "password": "secret99",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Registration is account CREATION only — it must never authenticate.
    assert "token" not in body
    user = body["user"]
    assert user["studentCode"] == "S-ADA1"
    assert user["facultyId"] == "ENGINEERING"
    assert user["facultyName"] == "Engineering"
    assert user["points"] == 0


def test_register_does_not_authenticate(client):
    """The created account must not hold a usable session: no token comes
    back and the fresh credentials alone (without /auth/login) grant
    nothing."""
    from app.database import SessionLocal

    r = client.post(
        "/api/v1/auth/register",
        json={
            "name": "No Session",
            "email": "nosession@uni.edu",
            "facultyId": "ENGINEERING",
            "password": "secret99",
        },
    )
    assert r.status_code == 201
    assert "token" not in r.json()
    with SessionLocal() as db:
        from app.models import User

        row = db.query(User).filter(User.email == "nosession@uni.edu").one()
        assert row.points == 0
    # The response identity cannot be used as a bearer session.
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 401


def test_register_duplicate_email_conflict(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "Duplicate", "email": DEMO_EMAIL, "facultyId": "ENGINEERING", "password": "secret99"},
    )
    assert r.status_code == 409


def test_register_unknown_faculty_rejected(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "X", "email": "x@uni.edu", "facultyId": "nope", "password": "secret99"},
    )
    assert r.status_code == 422


def test_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": "wrong"})
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_flutter_user_shape(client, auth):
    r = client.get("/api/v1/auth/me", headers=auth)
    assert r.status_code == 200
    user = r.json()["user"]
    # Flutter AppUser contract fields.
    for key in ("id", "studentCode", "name", "facultyId", "facultyName", "points"):
        assert key in user


def test_users_me_matches(client, auth):
    r = client.get("/api/v1/users/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["user"]["email" if "email" in r.json()["user"] else "name"] == "Demo Student"


def test_logout_returns_status(client, auth):
    r = client.post("/api/v1/auth/logout", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "logged_out"


def test_operation_id_format(plastic_prediction, client, auth):
    # Session creation mints a unique OP-YYYYMMDD-NNNNNN id.
    r = client.post(
        "/api/v1/deposit/session",
        headers=auth,
        json={"ai_prediction_id": plastic_prediction["prediction_id"], "station_id": "st-001"},
    )
    assert r.status_code == 200, r.text
    op = r.json()["operation_id"]
    assert re.fullmatch(r"OP-\d{8}-\d{6}", op), op

def test_register_with_explicit_student_code(client):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Ada Coded",
            "email": "ada2@uni.edu",
            "studentCode": "S-2024-0137",
            "facultyId": "ENGINEERING",
            "password": "secret99",
        },
    )
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["studentCode"] == "S-2024-0137"
    assert user["avatarVersion"] == 0


def test_register_duplicate_student_code_gets_suffix(client):
    first = client.post(
        "/api/v1/auth/register",
        json={"name": "One", "email": "one@uni.edu", "studentCode": "S-DUP",
              "facultyId": "ENGINEERING", "password": "secret99"},
    ).json()["user"]["studentCode"]
    assert first == "S-DUP"
    second = client.post(
        "/api/v1/auth/register",
        json={"name": "Two", "email": "two@uni.edu", "studentCode": "S-DUP",
              "facultyId": "ENGINEERING", "password": "secret99"},
    ).json()["user"]["studentCode"]
    assert second != "S-DUP" and second.startswith("S-DUP")
