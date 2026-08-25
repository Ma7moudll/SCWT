"""Rewards marketplace service — atomic, idempotent redemptions.

POINTS INTEGRITY CONTRACT
=========================
`redeem` runs inside ONE database transaction and enforces every invariant
below; any failure raises before COMMIT so there is never partial state:

1. reward exists, is_active, has stock (when limited)
2. balance check + deduction happen in a single conditional UPDATE:
       UPDATE users SET points = points - :cost
        WHERE id = :user AND points >= :cost
   rowcount 0 -> insufficient balance or concurrent spend -> ROLLBACK.
   Points can NEVER go negative, even under parallel requests.
3. idempotency_key (client-supplied) is unique per user at the DB level;
   a retry with the same key returns the ORIGINAL redemption untouched.
4. code-type rewards get a cryptographically random, unguessable code in a
   collision-safe loop. Cash rewards store only the payout destination.

Nothing here talks to any payment provider — fulfillment is an explicit,
verified admin action.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Reward, RewardRedemption, User

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I — unambiguous
CODE_LEN = 6
CASH_CATEGORIES = {"cash"}


class RewardError(Exception):
    """User-facing redemption failure; message is shown as-is."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def generate_code(db: Session) -> str:
    """Unique ECO-XXXXXX code (24^6 ≈ 191M space, retried on collision)."""
    for _ in range(10):
        body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        code = f"ECO-{body}"
        exists = db.execute(
            select(RewardRedemption.id).where(RewardRedemption.redemption_code == code)
        ).scalar_one_or_none()
        if exists is None:
            return code
    raise RewardError("Could not allocate a unique reward code. Please try again.")


def _status_for(reward: Reward) -> str:
    if reward.category in CASH_CATEGORIES:
        return "pending"
    return "available"


def _restore_reserved_stock(db: Session, reward_id: str) -> None:
    """Return one reserved unit to a limited-stock reward.

    Called ONLY from inside a transaction that won the atomic status
    transition (cancelled/rejected), so exactly one unit is restored per
    redemption no matter how many competing attempts occur. Unlimited-stock
    rewards (stock IS NULL) match zero rows and stay unlimited."""
    db.execute(
        update(Reward)
        .where(Reward.id == reward_id, Reward.stock.is_not(None))
        .values(stock=Reward.stock + 1)
    )


def redeem(
    db: Session,
    *,
    user_id: str,
    reward_id: str,
    idempotency_key: str,
    destination: str | None = None,
) -> RewardRedemption:
    # ---- idempotency first: same key returns the original redemption -------
    existing = db.execute(
        select(RewardRedemption).where(
            RewardRedemption.user_id == user_id,
            RewardRedemption.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    reward = db.get(Reward, reward_id)
    if reward is None:
        raise RewardError("This reward does not exist.", 404)
    if not reward.is_active:
        raise RewardError("This reward is no longer available.")
    if reward.points_cost <= 0:
        raise RewardError("This reward is misconfigured. Please contact support.")

    if reward.requires_destination and not (destination or "").strip():
        raise RewardError("Enter your payout number to redeem this reward.")
    if destination and len(destination.strip()) > 128:
        raise RewardError("That payout number is too long.")

    if reward.stock is not None:
        # Atomic stock reservation: prevents oversell under concurrency.
        result = db.execute(
            update(Reward)
            .where(Reward.id == reward.id, Reward.stock > 0)
            .values(stock=Reward.stock - 1)
        )
        if result.rowcount == 0:
            raise RewardError("This reward just sold out.")

    # ---- THE balance guard: single conditional UPDATE ----------------------
    result = db.execute(
        update(User)
        .where(User.id == user_id, User.points >= reward.points_cost)
        .values(points=User.points - reward.points_cost)
    )
    if result.rowcount == 0:
        raise RewardError(
            "You do not have enough points for this reward yet.", 409
        )

    redemption = RewardRedemption(
        id=str(uuid.uuid4())[:8],
        user_id=user_id,
        reward_id=reward.id,
        points_spent=reward.points_cost,
        status=_status_for(reward),
        redemption_code=None if reward.category in CASH_CATEGORIES else generate_code(db),
        destination=destination.strip() if destination else None,
        idempotency_key=idempotency_key,
    )
    db.add(redemption)

    try:
        db.commit()
    except Exception:
        db.rollback()
        # Concurrent duplicate key? Re-fetch the winner's redemption.
        existing = db.execute(
            select(RewardRedemption).where(
                RewardRedemption.user_id == user_id,
                RewardRedemption.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        raise

    db.refresh(redemption)
    return redemption


def admin_reject(db: Session, redemption: RewardRedemption, note: str) -> None:
    """Rejecting refunds the points — students never lose points to a
    rejection they did not cause. Auditable via admin_note.

    The refund is gated by an ATOMIC state transition: the conditional
    UPDATE only matches a row still in pending/approved, so of two
    concurrent rejections (or a rejection racing a student cancel) exactly
    one transaction wins the row and refunds; the loser updates zero rows,
    raises without touching points, and the whole unit rolls back."""
    won = db.execute(
        update(RewardRedemption)
        .where(
            RewardRedemption.id == redemption.id,
            RewardRedemption.status.in_(("pending", "approved")),
        )
        .values(status="rejected")
        .execution_options(synchronize_session=False)
    )
    if won.rowcount == 0:
        raise RewardError("Only pending or approved redemptions can be rejected.", 409)
    refund = db.execute(
        update(User)
        .where(User.id == redemption.user_id)
        .values(points=User.points + redemption.points_spent)
    )
    if refund.rowcount == 0:
        # Nothing has been committed yet — the status transition above rolls
        # back with this raise, so the redemption stays in its prior state.
        raise RewardError("The student account no longer exists.", 404)
    redemption.status = "rejected"
    redemption.admin_note = note[:512]
    redemption.fulfilled_at = datetime.now(timezone.utc)
    # The rejected payout never left inventory — restore the reserved unit
    # in the same transaction as the transition and the refund.
    _restore_reserved_stock(db, redemption.reward_id)
    db.commit()


def user_cancel_available(db: Session, redemption: RewardRedemption) -> None:
    """Cancel an unused AVAILABLE code and refund the points.

    Atomic transition: the refund happens ONLY in the transaction whose
    conditional UPDATE moved available -> cancelled (rowcount == 1). A
    concurrent transaction that read the same 'available' state loses the
    race — its UPDATE matches zero rows, it raises before refunding, and
    no points can be created from nothing."""
    won = db.execute(
        update(RewardRedemption)
        .where(
            RewardRedemption.id == redemption.id,
            RewardRedemption.status == "available",
        )
        .values(status="cancelled")
        .execution_options(synchronize_session=False)
    )
    if won.rowcount == 0:
        raise RewardError("Only available codes can be cancelled.")
    redemption.status = "cancelled"
    db.execute(
        update(User)
        .where(User.id == redemption.user_id)
        .values(points=User.points + redemption.points_spent)
    )
    # The unused code's reserved unit goes back on the shelf — atomically
    # with the transition and the refund (single commit below).
    _restore_reserved_stock(db, redemption.reward_id)
    db.commit()
