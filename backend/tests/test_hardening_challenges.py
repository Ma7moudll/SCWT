"""Challenge rewards (T18): a validated deposit that pushes the user past an
active challenge target awards the bonus EXACTLY ONCE, in the same
transaction as the base points; completion is per user and persisted."""
from __future__ import annotations

from app.database import SessionLocal
from app.models import Challenge, User, UserChallenge

from .conftest import FakeAi, _predict, confirm_event
from .test_deposit import create_session, complete


def _seed_challenge(target_kg: float = 0.01, reward: int = 25) -> str:
    with SessionLocal() as db:
        challenge = Challenge(
            id="ch-test-1",
            title="First Plastic",
            description="Deposit your first plastic",
            theme_emoji="♻️",
            waste_class="plastic",
            target_kg=target_kg,
            reward_points=reward,
            active=True,
        )
        db.merge(challenge)
        db.commit()
        return challenge.id


def _demo_user() -> User:
    with SessionLocal() as db:
        return db.query(User).filter(User.email == "demo@ecolamp.campus").first()


def test_completed_challenge_awards_bonus_once(
    client, auth, demo_session, publisher, monkeypatch
):
    _seed_challenge()
    points_before = _demo_user().points

    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, {"Authorization": f"Bearer {demo_session}"}, pred)
    status, body = complete(client, session["operation_id"])
    assert status == 200

    # The deposit result carries the bonus so the UI can show it.
    assert body.get("challenge_bonus", 0) >= 25 or body.get("points_awarded", 0) > 5

    # A second identical event for the same operation must not re-award.
    status2, body2 = complete(client, session["operation_id"])
    assert status2 == 409  # duplicate terminal events are rejected

    # Exactly one completion row exists (schema-level idempotency).
    with SessionLocal() as db:
        rows = (
            db.query(UserChallenge)
            .filter(
                UserChallenge.user_id == "u-demo",
                UserChallenge.challenge_id == "ch-test-1",
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].reward_points == 25

        # Base + bonus landed once.
        user = db.get(User, "u-demo")
        assert user.points == points_before + 5 + 25


def test_bonus_not_awarded_twice_across_deposits(
    client, auth, demo_session, publisher, monkeypatch
):
    _seed_challenge()

    for i in range(2):
        pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
        session = create_session(
            client, {"Authorization": f"Bearer {demo_session}"}, pred
        )
        status, body = complete(client, session["operation_id"])
        assert status == 200

    with SessionLocal() as db:
        rows = (
            db.query(UserChallenge)
            .filter(
                UserChallenge.user_id == "u-demo",
                UserChallenge.challenge_id == "ch-test-1",
            )
            .all()
        )
        # The first deposit completed it; the second must NOT add another row.
        assert len(rows) == 1


def test_challenge_list_reflects_persisted_completion(
    client, auth, demo_session, publisher, monkeypatch
):
    _seed_challenge()
    before = client.get("/api/v1/challenges", headers=auth).json()["items"]
    entry = next(c for c in before if c["id"] == "ch-test-1")
    assert entry["completed"] is False

    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, {"Authorization": f"Bearer {demo_session}"}, pred)
    complete(client, session["operation_id"])

    after = client.get("/api/v1/challenges", headers=auth).json()["items"]
    entry = next(c for c in after if c["id"] == "ch-test-1")
    assert entry["completed"] is True


def test_other_users_are_not_affected_by_someone_elses_completion(
    client, auth, demo_session, publisher, monkeypatch
):
    _seed_challenge()
    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, {"Authorization": f"Bearer {demo_session}"}, pred)
    complete(client, session["operation_id"])

    # Register a fresh user; they have NOT completed anything.
    from .conftest import register_and_login
    other_auth = register_and_login(client, "fresh@recycle.vision", "password123")
    items = client.get("/api/v1/challenges", headers=other_auth).json()["items"]
    entry = next(c for c in items if c["id"] == "ch-test-1")
    assert entry["completed"] is False
