"""Rewards marketplace (T24): catalog browsing, atomic idempotent redemption,
code vs cash flows, admin fulfillment queue, and points integrity under
concurrency. The balance can never go negative and a retried redeem can
never double-spend."""
from __future__ import annotations

import threading

import pytest

from app.database import SessionLocal
from app.models import User
from app.security import hash_password
from app.services.reward_service import RewardError


@pytest.fixture
def student(client):
    """Fresh student with 120 points — enough for coffee (60) + printing (80)
    is NOT affordable; tests control exact balances via _set_points."""
    with SessionLocal() as db:
        db.add(
            User(
                id="u-reward",
                email="reward@recycle.vision",
                student_code="S-REWARD",
                name="Reward Student",
                password_hash=hash_password("reward-pass-123"),
                faculty_id="ENGINEERING",
                points=0,
            )
        )
        db.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "reward@recycle.vision", "password": "reward-pass-123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _set_points(user_id: str, points: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.points = points
        db.commit()


def _balance(user_id: str = "u-reward") -> int:
    with SessionLocal() as db:
        return int(db.get(User, user_id).points)


# -- catalog -------------------------------------------------------------------


def test_catalog_lists_seeded_rewards_with_balance(client, student):
    r = client.get("/api/v1/rewards", headers=student)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance"] == 0
    ids = {item["id"] for item in body["rewards"]}
    assert {"rw-vodafone-10", "rw-instapay-25", "rw-mix-coffee-20", "rw-copy-center-30"} <= ids
    vodafone = [i for i in body["rewards"] if i["id"] == "rw-vodafone-10"][0]
    assert vodafone["requires_destination"] is True
    assert vodafone["category"] == "cash"


def test_catalog_requires_auth(client):
    r = client.get("/api/v1/rewards")
    assert r.status_code == 401


# -- code flow (coffee discount) -------------------------------------------------


def test_redeem_deducts_points_and_issues_code(client, student):
    _set_points("u-reward", 60)
    r = client.post(
        "/api/v1/rewards/rw-mix-coffee-20/redeem",
        headers=student,
        json={"idempotency_key": "11111111-1111-1111-1111-111111111111"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balance"] == 0
    rd = body["redemption"]
    assert rd["status"] == "available"
    assert rd["redemption_code"] and rd["redemption_code"].startswith("ECO-")
    assert _balance() == 0


def test_insufficient_balance_is_refused_without_state_change(client, student):
    _set_points("u-reward", 59)
    r = client.post(
        "/api/v1/rewards/rw-mix-coffee-20/redeem",
        headers=student,
        json={"idempotency_key": "22222222-2222-2222-2222-222222222222"},
    )
    assert r.status_code == 409
    assert "enough points" in r.json()["error"].lower()
    assert _balance() == 59  # untouched


def test_idempotent_retry_returns_original_redemption(client, student):
    _set_points("u-reward", 200)
    key = "33333333-3333-3333-3333-333333333333"
    payload = {"idempotency_key": key}
    first = client.post("/api/v1/rewards/rw-mix-coffee-20/redeem", headers=student, json=payload)
    retry = client.post("/api/v1/rewards/rw-mix-coffee-20/redeem", headers=student, json=payload)
    other = client.post("/api/v1/rewards/rw-copy-center-30/redeem", headers=student, json=payload)
    assert first.status_code == 200 and retry.status_code == 200
    assert first.json()["redemption"]["id"] == retry.json()["redemption"]["id"]
    # Same key against a DIFFERENT reward also returns the original — never a second spend.
    assert other.status_code == 200
    assert other.json()["redemption"]["id"] == first.json()["redemption"]["id"]
    assert _balance() == 200 - 60  # one deduction only


def test_parallel_redeems_cannot_overspend_balance(client, student):
    """10 concurrent redemptions of a 60-point reward against a 240-point
    balance: exactly 4 succeed, the rest are refused, final balance is
    exactly 0 — no lost updates, nothing negative."""
    _set_points("u-reward", 240)
    results: list[int] = []
    lock = threading.Lock()

    def fire(i: int) -> None:
        from app.services.reward_service import redeem

        with SessionLocal() as db:
            try:
                redeem(db, user_id="u-reward", reward_id="rw-mix-coffee-20",
                       idempotency_key=f"parallel-{i:03d}-aaaaaaaaaaaa")
                outcome = 200
            except RewardError as exc:
                outcome = exc.status_code
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = results.count(200)
    assert ok == 4, results
    assert _balance() == 0  # 4 x 60 spent; nothing lost, nothing negative


def test_codes_are_unique_per_redemption(client, student):
    _set_points("u-reward", 600)
    codes = set()
    for i in range(3):
        r = client.post(
            "/api/v1/rewards/rw-mix-coffee-20/redeem",
            headers=student,
            json={"idempotency_key": f"unique-codes-{i}-aaaaaaaaaa"},
        )
        assert r.status_code == 200, r.text
        codes.add(r.json()["redemption"]["redemption_code"])
    assert len(codes) == 3


def test_cancel_available_code_refunds_points(client, student):
    _set_points("u-reward", 60)
    r = client.post(
        "/api/v1/rewards/rw-mix-coffee-20/redeem",
        headers=student,
        json={"idempotency_key": "cancel-0001-aaaaaaaaaaaa"},
    )
    rd_id = r.json()["redemption"]["id"]
    cancel = client.post(f"/api/v1/rewards/redemptions/{rd_id}/cancel", headers=student)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["redemption"]["status"] == "cancelled"
    assert cancel.json()["balance"] == 60


def test_cancel_twice_or_on_used_is_refused(client, student):
    _set_points("u-reward", 60)
    r = client.post(
        "/api/v1/rewards/rw-mix-coffee-20/redeem",
        headers=student,
        json={"idempotency_key": "cancel-0002-aaaaaaaaaaaa"},
    )
    rd_id = r.json()["redemption"]["id"]
    client.post(f"/api/v1/rewards/redemptions/{rd_id}/cancel", headers=student)
    again = client.post(f"/api/v1/rewards/redemptions/{rd_id}/cancel", headers=student)
    assert again.status_code == 422


def test_user_cannot_see_or_cancel_someone_elses_redemption(client, student, auth):
    _set_points("u-reward", 60)
    r = client.post(
        "/api/v1/rewards/rw-mix-coffee-20/redeem",
        headers=student,
        json={"idempotency_key": "cross-user-1-aaaaaaaaaaa"},
    )
    rd_id = r.json()["redemption"]["id"]
    # `auth` fixture is the demo user — a different account.
    foreign_get = client.get("/api/v1/rewards/redemptions", headers=auth)
    ids = [i["id"] for i in foreign_get.json()["redemptions"]]
    assert rd_id not in ids
    foreign_cancel = client.post(f"/api/v1/rewards/redemptions/{rd_id}/cancel", headers=auth)
    assert foreign_cancel.status_code == 404


def test_cash_reward_requires_destination(client, student):
    _set_points("u-reward", 100)
    r = client.post(
        "/api/v1/rewards/rw-vodafone-10/redeem",
        headers=student,
        json={"idempotency_key": "cash-nodest-1-aaaaaaaaa"},
    )
    assert r.status_code == 422
    assert "payout number" in r.json()["error"].lower()
    assert _balance() == 100


# -- cash flow + admin queue ------------------------------------------------------


@pytest.fixture
def admin_auth(client):
    with SessionLocal() as db:
        if db.query(User).filter(User.email == "admin@recycle.vision").first() is None:
            db.add(
                User(
                    id="u-admin",
                    email="admin@recycle.vision",
                    student_code="S-ADMIN",
                    name="Admin",
                    password_hash=hash_password("admin-pass-123"),
                    faculty_id="ENGINEERING",
                    points=0,
                    role="admin",
                )
            )
            db.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@recycle.vision", "password": "admin-pass-123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _redeem_vodafone(client, student, key="cash-flow-1-aaaaaaaaaaa") -> str:
    _set_points("u-reward", 100)
    r = client.post(
        "/api/v1/rewards/rw-vodafone-10/redeem",
        headers=student,
        json={"idempotency_key": key, "destination": "01012345678"},
    )
    assert r.status_code == 200, r.text
    return r.json()["redemption"]["id"]


def test_student_cannot_access_admin_queue(client, student):
    r = client.get("/api/v1/admin/rewards/redemptions", headers=student)
    assert r.status_code == 403


def test_cash_redemption_lands_pending_in_admin_queue(client, student, admin_auth):
    rd_id = _redeem_vodafone(client, student)
    r = client.get("/api/v1/admin/rewards/redemptions?status=pending", headers=admin_auth)
    assert r.status_code == 200, r.text
    items = [i for i in r.json()["items"] if i["id"] == rd_id]
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "pending"
    assert item["destination_masked"].startswith("010")
    assert "*" in item["destination_masked"] and not item["destination_masked"].endswith(
        "01012345678"
    )  # masked, not raw
    assert item["student"]["email"] == "reward@recycle.vision"


def test_approve_then_fulfill_flow(client, student, admin_auth):
    rd_id = _redeem_vodafone(client, student)
    approve = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/approve",
        headers=admin_auth,
        json={"admin_note": ""},
    )
    assert approve.status_code == 200 and approve.json()["status"] == "approved"
    fulfill = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/fulfill",
        headers=admin_auth,
        json={"admin_note": "sent via Vodafone Cash portal"},
    )
    assert fulfill.status_code == 200 and fulfill.json()["status"] == "fulfilled"
    mine = client.get("/api/v1/rewards/redemptions", headers=student).json()["redemptions"]
    assert mine[0]["status"] == "fulfilled"


def test_reject_refunds_points_exactly_once(client, student, admin_auth):
    rd_id = _redeem_vodafone(client, student, key="reject-flow-1-aaaaaaaaa")
    before = _balance()
    reject = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/reject",
        headers=admin_auth,
        json={"admin_note": "wallet unreachable"},
    )
    assert reject.status_code == 200 and reject.json()["status"] == "rejected"
    after_first = _balance()
    assert after_first == before + 100
    # Rejecting again must not double-refund.
    reject_again = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/reject",
        headers=admin_auth,
        json={"admin_note": "retry"},
    )
    assert reject_again.status_code == 409
    assert _balance() == after_first


def test_fulfilled_redemption_cannot_be_rejected_after(client, student, admin_auth):
    rd_id = _redeem_vodafone(client, student, key="fulfill-lock-1-aaaaaaaa")
    client.post(f"/api/v1/admin/rewards/redemptions/{rd_id}/fulfill", headers=admin_auth, json={})
    reject = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/reject", headers=admin_auth, json={}
    )
    assert reject.status_code == 409


# -- catalog management ------------------------------------------------------------


def test_admin_can_create_update_deactivate_reward(client, admin_auth):
    create = client.post(
        "/api/v1/admin/rewards",
        headers=admin_auth,
        json={
            "category": "discount",
            "name": "Cafeteria Combo",
            "points_cost": 150,
            "value_label": "15% OFF",
            "stock": 5,
        },
    )
    assert create.status_code == 200, create.text
    reward_id = create.json()["id"]

    patch = client.patch(
        f"/api/v1/admin/rewards/{reward_id}",
        headers=admin_auth,
        json={
            "category": "discount",
            "name": "Cafeteria Combo",
            "points_cost": 140,
            "value_label": "15% OFF",
            "is_active": False,
            "stock": 5,
        },
    )
    assert patch.status_code == 200 and patch.json()["is_active"] is False

    # Deactivated rewards vanish from the student catalog.
    catalog_ids = [
        i["id"] for i in client.get("/api/v1/rewards", headers=admin_auth).json()["rewards"]
    ]
    assert reward_id not in catalog_ids


def test_cash_reward_requires_destination_flag(client, admin_auth):
    r = client.post(
        "/api/v1/admin/rewards",
        headers=admin_auth,
        json={"category": "cash", "name": "Bad Cash", "points_cost": 10, "value_label": "1 EGP"},
    )
    assert r.status_code == 422


def test_delete_blocked_when_history_exists(client, student, admin_auth):
    rd_id = _redeem_vodafone(client, student, key="del-guard-1-aaaaaaaaaaa")
    del_ok = client.delete("/api/v1/admin/rewards/rw-instapay-25", headers=admin_auth)
    assert del_ok.status_code == 200
    del_used = client.delete("/api/v1/admin/rewards/rw-vodafone-10", headers=admin_auth)
    assert del_used.status_code == 409
    assert "deactivate" in del_used.json()["error"].lower()
    # Redemption history still intact.
    mine = client.get("/api/v1/rewards/redemptions", headers=student).json()["redemptions"]
    assert any(i["id"] == rd_id for i in mine)


def test_stock_is_atomic_and_blocks_sold_out(client, student, admin_auth):
    create = client.post(
        "/api/v1/admin/rewards",
        headers=admin_auth,
        json={
            "category": "food",
            "name": "Limited Snack",
            "points_cost": 10,
            "value_label": "Snack",
            "stock": 1,
        },
    )
    reward_id = create.json()["id"]

    with SessionLocal() as db:
        db.add_all(
            [
                User(
                    id=f"u-stock-{i}",
                    email=f"stock{i}@recycle.vision",
                    student_code=f"S-STOCK{i}",
                    name=f"Stock {i}",
                    password_hash=hash_password("stock-pass-123"),
                    faculty_id="ENGINEERING",
                    points=50,
                )
                for i in range(2)
            ]
        )
        db.commit()

    tokens = []
    for i in range(2):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": f"stock{i}@recycle.vision", "password": "stock-pass-123"},
        )
        tokens.append({"Authorization": f"Bearer {r.json()['token']}"})

    outcomes = []
    for tok in tokens:
        r = client.post(
            f"/api/v1/rewards/{reward_id}/redeem",
            headers=tok,
            json={"idempotency_key": f"stock-race-{tokens.index(tok)}-aaaaaaa"},
        )
        outcomes.append(r.status_code)
    assert sorted(outcomes) == [200, 422]  # one wins, one sees sold out


# -- double-refund race regression (atomic state transitions) --------------------
#
# The original TOCTOU: two transactions each loaded a redemption while it was
# still in its pre-transition state, then BOTH refunded — points created from
# nothing. These tests reproduce that interleaving deterministically: the
# "loser" session loads its snapshot BEFORE the winner commits, so its in-
# memory copy still shows the old status when it attempts the same transition.
# The atomic guarded UPDATE must match zero rows for the loser -> no refund.


def _redeem_code(client, student, key: str) -> str:
    """Redeem the coffee CODE reward at 100 points; returns redemption id."""
    _set_points("u-reward", 100)
    r = client.post(
        "/api/v1/rewards/rw-mix-coffee-20/redeem",
        headers=student,
        json={"idempotency_key": key},
    )
    assert r.status_code == 200, r.text
    return r.json()["redemption"]["id"]


def _redeem_cash(client, student, key: str) -> str:
    """Redeem the InstaPay CASH reward at 250 points; returns redemption id."""
    _set_points("u-reward", 250)
    r = client.post(
        "/api/v1/rewards/rw-instapay-25/redeem",
        headers=student,
        json={"idempotency_key": key, "destination": "01012345678"},
    )
    assert r.status_code == 200, r.text
    return r.json()["redemption"]["id"]


def test_concurrent_cancels_refund_exactly_once(client, student):
    """Case A — cancel VS cancel on the same available code: one winner
    refunds once; the stale-snapshot loser is a no-op."""
    from app.models import RewardRedemption
    from app.services.reward_service import user_cancel_available

    rd_id = _redeem_code(client, student, "race-cancel-000000001")
    after_redeem = _balance()  # 40

    with SessionLocal() as loser:
        stale = loser.get(RewardRedemption, rd_id)
        assert stale.status == "available"  # TOCTOU precondition

        with SessionLocal() as winner:
            user_cancel_available(winner, winner.get(RewardRedemption, rd_id))

        with pytest.raises(RewardError):
            user_cancel_available(loser, stale)

    assert _balance() == after_redeem + 60, "exactly ONE refund of 60, never two"
    with SessionLocal() as s:
        assert s.get(RewardRedemption, rd_id).status == "cancelled"


def test_stale_admin_reject_cannot_double_refund(client, student):
    """Case B — reject VS reject on the same pending cash payout: the second
    rejection must be refused without moving points again."""
    from app.models import RewardRedemption
    from app.services.reward_service import admin_reject

    rd_id = _redeem_cash(client, student, "race-reject-000000001")
    after_redeem = _balance()  # 0

    with SessionLocal() as loser:
        stale = loser.get(RewardRedemption, rd_id)
        assert stale.status == "pending"

        with SessionLocal() as winner:
            admin_reject(winner, winner.get(RewardRedemption, rd_id), "winner")

        with pytest.raises(RewardError):
            admin_reject(loser, stale, "loser must not refund again")

    assert _balance() == after_redeem + 250, "exactly ONE refund of 250"
    with SessionLocal() as s:
        row = s.get(RewardRedemption, rd_id)
        assert row.status == "rejected"
        assert row.admin_note == "winner", "loser note must not overwrite"


def test_cancel_vs_mark_used_single_terminal_transition(client, student):
    """Case C — cancel VS mark-used share the 'available' source state:
    exactly one of them may win; the other is refused."""
    from app.models import RewardRedemption

    # cancel wins, mark-used loses
    rd_id = _redeem_code(client, student, "race-cxm-0000000001")
    balance_after_win = None
    win = client.post(f"/api/v1/rewards/redemptions/{rd_id}/cancel", headers=student)
    assert win.status_code == 200
    balance_after_win = _balance()
    lost = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/mark-used",
        headers=_admin_headers(client),
    )
    assert lost.status_code == 409
    assert _balance() == balance_after_win, "mark-used must not touch points"
    with SessionLocal() as s:
        assert s.get(RewardRedemption, rd_id).status == "cancelled"

    # mark-used wins, cancel loses
    rd2 = _redeem_code(client, student, "race-cxm-0000000002")
    used = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd2}/mark-used",
        headers=_admin_headers(client),
    )
    assert used.status_code == 200
    balance_before = _balance()
    lost_cancel = client.post(f"/api/v1/rewards/redemptions/{rd2}/cancel", headers=student)
    assert lost_cancel.status_code == 422
    assert _balance() == balance_before, "losing cancel must not refund"
    with SessionLocal() as s:
        assert s.get(RewardRedemption, rd2).status == "used"


def _admin_headers(client) -> dict:
    with SessionLocal() as db:
        from app.models import User

        if db.get(User, "u-admin-race") is None:
            db.add(
                User(
                    id="u-admin-race",
                    email="race-admin@recycle.vision",
                    student_code="S-RACEADMIN",
                    name="Race Admin",
                    password_hash=hash_password("admin-pass-123"),
                    faculty_id="ENGINEERING",
                    points=0,
                    role="admin",
                )
            )
            db.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "race-admin@recycle.vision", "password": "admin-pass-123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_parallel_cancels_through_http_refund_exactly_once(client, student):
    """True concurrency: N threads fire cancel simultaneously through real
    HTTP; exactly one may succeed and only one refund may land."""
    import threading

    rd_id = _redeem_code(client, student, "race-parallel-00000001")
    after_redeem = _balance()

    barrier = threading.Barrier(8)
    outcomes: list[int] = []
    lock = threading.Lock()

    def fire():
        barrier.wait()
        r = client.post(f"/api/v1/rewards/redemptions/{rd_id}/cancel", headers=student)
        with lock:
            outcomes.append(r.status_code)

    threads = [threading.Thread(target=fire) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count(200) == 1, f"exactly one winner: {outcomes}"
    assert all(code in (409, 422) for code in outcomes if code != 200)
    assert _balance() == after_redeem + 60, "exactly one refund under contention"


# -- stock reservation/restoration lifecycle --------------------------------------
#
# Invariant: available stock + active reservations + consumed inventory
# equals original inventory. A redemption reserves one unit; cancelling or
# rejecting an UNUSED redemption returns that unit; consumption never does.
# Restoration rides the same winning atomic transition as the refund, so a
# unit can never be returned twice.


def _make_limited_code_reward(stock):
    with SessionLocal() as db:
        from app.models import Reward

        row = db.get(Reward, "rw-limited-code")
        if row is not None:
            row.stock = stock
        else:
            db.add(
                Reward(
                    id="rw-limited-code",
                    category="food",
                    name="Limited Coffee",
                    description="",
                    provider="MIX",
                    points_cost=60,
                    value_label="20% OFF",
                    currency="EGP",
                    icon="local_cafe",
                    is_active=True,
                    stock=stock,
                    requires_destination=False,
                )
            )
        db.commit()
    return "rw-limited-code"


def _make_limited_cash_reward(stock):
    with SessionLocal() as db:
        from app.models import Reward

        db.add(
            Reward(
                id="rw-limited-cash",
                category="cash",
                name="Limited Cashout",
                description="",
                provider="Vodafone",
                points_cost=50,
                value_label="5 EGP VC",
                currency="EGP",
                icon="card_giftcard",
                is_active=True,
                stock=stock,
                requires_destination=True,
            )
        )
        db.commit()
    return "rw-limited-cash"


def _stock(reward_id):
    with SessionLocal() as db:
        from app.models import Reward

        return db.get(Reward, reward_id).stock


def _redeem_limited(client, student, reward_id, key, dest=None, points=100):
    _set_points("u-reward", points)
    r = client.post(
        "/api/v1/rewards/%s/redeem" % reward_id,
        headers=student,
        json=dict(idempotency_key=key, **({"destination": dest} if dest else {})),
    )
    assert r.status_code == 200, r.text
    return r.json()["redemption"]


def test_redeem_decrements_stock_exactly_once(client, student):
    _make_limited_code_reward(10)
    _redeem_limited(client, student, "rw-limited-code", "stock-dec-0000001")
    assert _stock("rw-limited-code") == 9


def test_cancel_restores_reserved_stock(client, student):
    _make_limited_code_reward(10)
    rd = _redeem_limited(client, student, "rw-limited-code", "stock-can-0000001")
    assert _stock("rw-limited-code") == 9

    r = client.post("/api/v1/rewards/redemptions/%s/cancel" % rd["id"], headers=student)
    assert r.status_code == 200
    assert _stock("rw-limited-code") == 10, "cancelled reservation must return"
    assert _balance() == 100, "refunded exactly once (100 -> 40 -> 100)"


def test_admin_reject_restores_reserved_stock(client, student):
    from app.models import RewardRedemption
    from app.services.reward_service import admin_reject

    _make_limited_cash_reward(10)
    rd = _redeem_limited(
        client, student, "rw-limited-cash", "stock-rej-0000001", dest="01012345678"
    )
    assert _stock("rw-limited-cash") == 9
    before = _balance()

    with SessionLocal() as s:
        admin_reject(s, s.get(RewardRedemption, rd["id"]), "cannot fulfill")

    assert _stock("rw-limited-cash") == 10, "rejected reservation must return"
    assert _balance() == before + 50, "refunded exactly once"


def test_used_redemption_never_restores_stock(client, student):
    _admin_headers(client)
    _make_limited_code_reward(10)
    rd = _redeem_limited(client, student, "rw-limited-code", "stock-use-0000001")

    r = client.post(
        "/api/v1/admin/rewards/redemptions/%s/mark-used" % rd["id"],
        headers=_admin_headers(client),
    )
    assert r.status_code == 200
    assert _stock("rw-limited-code") == 9, "consumed inventory stays consumed"

    # A used code can no longer be cancelled into a second refund/restore.
    lost = client.post(
        "/api/v1/rewards/redemptions/%s/cancel" % rd["id"], headers=student
    )
    assert lost.status_code == 422
    assert _stock("rw-limited-code") == 9


def test_concurrent_cancels_restore_stock_exactly_once(client, student):
    from app.models import RewardRedemption
    from app.services.reward_service import user_cancel_available

    _make_limited_code_reward(10)
    rd = _redeem_limited(client, student, "rw-limited-code", "stock-racec-00001")

    with SessionLocal() as loser:
        stale = loser.get(RewardRedemption, rd["id"])
        assert stale.status == "available"

        with SessionLocal() as winner:
            user_cancel_available(winner, winner.get(RewardRedemption, rd["id"]))

        with pytest.raises(RewardError):
            user_cancel_available(loser, stale)

    assert _stock("rw-limited-code") == 10, "one restore, never two (S+1)"
    assert _balance() == 100, "one refund, never two"


def test_concurrent_rejects_restore_stock_exactly_once(client, student):
    from app.models import RewardRedemption
    from app.services.reward_service import admin_reject

    _make_limited_cash_reward(10)
    rd = _redeem_limited(
        client, student, "rw-limited-cash", "stock-racer-00001", dest="01012345678"
    )
    before = _balance()

    with SessionLocal() as loser:
        stale = loser.get(RewardRedemption, rd["id"])
        assert stale.status == "pending"

        with SessionLocal() as winner:
            admin_reject(winner, winner.get(RewardRedemption, rd["id"]), "winner")

        with pytest.raises(RewardError):
            admin_reject(loser, stale, "loser")

    assert _stock("rw-limited-cash") == 10, "one restore, never two"
    assert _balance() == before + 50, "one refund, never two"


def test_cancel_vs_mark_used_stock_semantics(client, student):
    """If cancellation wins the race the unit returns; if consumption wins it
    never does. Stock can never exceed S either way."""
    _admin_headers(client)
    _make_limited_code_reward(10)
    rd = _redeem_limited(client, student, "rw-limited-code", "stock-cxu-0000001")

    win = client.post(
        "/api/v1/rewards/redemptions/%s/cancel" % rd["id"], headers=student
    )
    assert win.status_code == 200
    lost = client.post(
        "/api/v1/admin/rewards/redemptions/%s/mark-used" % rd["id"],
        headers=_admin_headers(client),
    )
    assert lost.status_code == 409
    assert _stock("rw-limited-code") == 10, "cancel won: restored exactly once"

    _make_limited_code_reward(10)  # reset stock for round two
    rd2 = _redeem_limited(client, student, "rw-limited-code", "stock-cxu-0000002")
    used = client.post(
        "/api/v1/admin/rewards/redemptions/%s/mark-used" % rd2["id"],
        headers=_admin_headers(client),
    )
    assert used.status_code == 200
    lost2 = client.post(
        "/api/v1/rewards/redemptions/%s/cancel" % rd2["id"], headers=student
    )
    assert lost2.status_code == 422
    assert _stock("rw-limited-code") == 9, "consumption won: unit stays consumed"
    assert _balance() == 40, "no refund when consumption wins"


def test_insufficient_stock_refuses_cleanly(client, student):
    _make_limited_code_reward(0)
    before = _balance()
    r = client.post(
        "/api/v1/rewards/rw-limited-code/redeem",
        headers=student,
        json={"idempotency_key": "stock-zero-00000001"},
    )
    assert r.status_code in (409, 422), r.text
    assert _stock("rw-limited-code") == 0, "failed redeem must not touch stock"
    assert _balance() == before, "failed redeem must not touch points"


# -- challenge bonus race (#3): losing a concurrent completion must never
# roll back the deposit's base points. The loser's UserChallenge insert hits
# the unique constraint inside a SAVEPOINT; only the bonus insert is undone.


def _make_tiny_challenge(client, admin_auth, title):
    r = client.post(
        "/api/v1/admin/challenges", headers=admin_auth,
        json={
            "title": title, "description": "race", "theme_emoji": "🧲",
            "waste_class": "plastic", "target_kg": 0.001, "reward_points": 5,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_concurrent_challenge_completion_keeps_base_points(
    client, admin_auth, auth, plastic_prediction
):
    """Deposit first, THEN create the challenge (progress >= target but never
    completed). Two transactions now race to claim it; the loser must keep its
    simulated base-point award and produce zero bonus."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Challenge as ChallengeModel
    from app.models import User, UserChallenge
    from app.services.challenge_service import ChallengeService

    from .test_user_data import confirm_deposit

    confirm_deposit(client, auth, plastic_prediction)  # crosses 0.001 kg target
    cid = _make_tiny_challenge(client, admin_auth, "Race Bonus")

    with SessionLocal() as winner:
        wuser = winner.execute(
            select(User).where(User.email == "demo@ecolamp.campus")
        ).scalar_one()
        bonus_w = ChallengeService().on_deposit_confirmed(winner, wuser, "plastic")
        winner.commit()
    assert bonus_w == 5

    # Loser holds a stale session that has NOT seen the winner's row.
    with SessionLocal() as loser:
        luser = loser.execute(
            select(User).where(User.email == "demo@ecolamp.campus")
        ).scalar_one()
        base = luser.points          # includes everything committed so far
        luser.points += 7            # simulate this deposit's BASE award
        bonus_l = ChallengeService().on_deposit_confirmed(loser, luser, "plastic")
        assert bonus_l == 0, "loser must not double-claim the bonus"
        loser.commit()

        refreshed = loser.get(User, luser.id)
        assert refreshed.points == base + 7, (
            "base award must survive the lost bonus race"
        )

    rows = SessionLocal().execute(
        select(UserChallenge).where(UserChallenge.challenge_id == cid)
    ).scalars().all()
    assert len(rows) == 1, "exactly one completion row"


def test_fulfill_is_cash_only(client, student, admin_auth):
    """Code rewards are consumed by merchants (mark-used), never 'fulfilled'
    by admins — the two lifecycles can no longer be mixed up."""
    rd_id = _redeem_code(client, student, "fulfill-cash-only-00001")
    r = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/fulfill", headers=admin_auth, json={}
    )
    assert r.status_code == 409, r.text

    # the code path still works end to end
    used = client.post(
        f"/api/v1/admin/rewards/redemptions/{rd_id}/mark-used", headers=admin_auth
    )
    assert used.status_code == 200 and used.json()["status"] == "used"
