"""Pagination (T24): limit/offset with total on history, challenges and
leaderboard; ceilings enforced server-side."""
from __future__ import annotations

from app.database import SessionLocal
from app.models import Challenge

from .conftest import FakeAi, _predict, confirm_event
from .test_deposit import create_session, complete


def _make_deposits(client, demo_session, publisher, monkeypatch, count: int) -> None:
    for _ in range(count):
        pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
        session = create_session(client, {"Authorization": f"Bearer {demo_session}"}, pred)
        status, body = complete(client, session["operation_id"])
        assert status == 200, body


def test_history_pagination_windows_and_total(client, auth, demo_session, publisher, monkeypatch):
    _make_deposits(client, demo_session, publisher, monkeypatch, 3)

    full = client.get("/api/v1/waste/history", headers=auth).json()
    assert full["total"] == 3

    page1 = client.get(
        "/api/v1/waste/history?limit=2&offset=0", headers=auth
    ).json()
    page2 = client.get(
        "/api/v1/waste/history?limit=2&offset=2", headers=auth
    ).json()
    assert len(page1["items"]) == 2 and len(page2["items"]) == 1
    assert page1["limit"] == 2 and page1["offset"] == 0
    ids = [e["operation_id"] for e in page1["items"]] + [
        e["operation_id"] for e in page2["items"]
    ]
    assert set(ids) == {e["operation_id"] for e in full["items"]}
    assert len(set(ids)) == 3  # no overlap


def test_history_limit_ceiling_enforced(client, auth):
    r = client.get("/api/v1/waste/history?limit=100000", headers=auth)
    assert r.status_code == 200
    assert r.json()["limit"] <= 100


def test_leaderboard_pagination(client, auth):
    r = client.get("/api/v1/leaderboard?limit=1&offset=0", headers=auth).json()
    assert {"entries", "total", "limit", "offset"} == set(r.keys())
    assert r["limit"] == 1


def test_challenges_pagination_shape(client, auth):
    with SessionLocal() as db:
        db.add(
            Challenge(
                id="ch-pag-1",
                title="Plastic Week",
                description="Deposit 10kg of plastic",
                theme_emoji="♻️",
                waste_class="plastic",
                target_kg=100.0,
                reward_points=50,
                active=True,
            )
        )
        db.commit()

    r = client.get("/api/v1/challenges?limit=10&offset=0", headers=auth).json()
    assert {"items", "total", "limit", "offset"} == set(r.keys())
    assert r["total"] >= 1
