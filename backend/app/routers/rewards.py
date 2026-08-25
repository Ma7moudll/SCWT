"""Rewards marketplace — student-facing endpoints.

GET  /rewards                     active catalog + my balance
GET  /rewards/redemptions         my redemption history
POST /rewards/{id}/redeem         atomic, idempotent redemption
POST /rewards/redemptions/{id}/cancel   cancel an unused code (points refunded)

Every failure surfaces as the uniform `{"error": "<sentence>"}` envelope via
the global handlers; RewardError carries its own status code.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Reward, RewardRedemption, User
from ..security import get_current_user
from ..services.reward_service import RewardError, redeem, user_cancel_available

router = APIRouter(prefix="/rewards", tags=["rewards"])


class RedeemRequest(BaseModel):
    # Client-generated UUID: one redemption per key per user — enforced by a
    # unique constraint so a retried request can never double-spend.
    idempotency_key: str
    destination: str | None = None

    @field_validator("idempotency_key")
    @classmethod
    def _key_shape(cls, v: str) -> str:
        v = v.strip()
        if not 8 <= len(v) <= 64:
            raise ValueError("Invalid redemption reference.")
        return v


def _reward_out(r: Reward) -> dict:
    return {
        "id": r.id,
        "category": r.category,
        "name": r.name,
        "description": r.description,
        "provider": r.provider,
        "points_cost": r.points_cost,
        "value_label": r.value_label,
        "currency": r.currency,
        "icon": r.icon,
        "stock": r.stock,  # None = unlimited
        "requires_destination": r.requires_destination,
    }


def _redemption_out(db: Session, rd: RewardRedemption, *, owner: bool) -> dict:
    reward = db.get(Reward, rd.reward_id)
    out = {
        "id": rd.id,
        "reward_id": rd.reward_id,
        "reward_name": reward.name if reward else rd.reward_id,
        "reward_category": reward.category if reward else "",
        "provider": reward.provider if reward else "",
        "value_label": reward.value_label if reward else "",
        "points_spent": rd.points_spent,
        "status": rd.status,
        "created_at": rd.created_at.isoformat() if rd.created_at else None,
        "fulfilled_at": rd.fulfilled_at.isoformat() if rd.fulfilled_at else None,
        "admin_note": rd.admin_note if rd.status == "rejected" else None,
    }
    if owner:
        # The merchant code is only ever shown to its owner. Cash payout
        # destinations are masked — the full value lives server-side only.
        out["redemption_code"] = rd.redemption_code
        if rd.destination:
            out["destination_masked"] = (
                rd.destination[:4] + "*" * max(len(rd.destination) - 7, 3)
                + rd.destination[-3:]
                if len(rd.destination) > 7
                else "***"
            )
    return out


@router.get("")
def list_rewards(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rewards = db.execute(
        select(Reward).where(Reward.is_active.is_(True)).order_by(Reward.points_cost)
    ).scalars().all()
    return {
        "balance": user.points,
        "rewards": [_reward_out(r) for r in rewards],
    }


@router.get("/redemptions")
def my_redemptions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rows = db.execute(
        select(RewardRedemption)
        .where(RewardRedemption.user_id == user.id)
        .order_by(RewardRedemption.created_at.desc())
        .limit(100)
    ).scalars().all()
    return {"redemptions": [_redemption_out(db, r, owner=True) for r in rows]}


@router.post("/{reward_id}/redeem")
def redeem_reward(
    reward_id: str,
    payload: RedeemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        rd = redeem(
            db,
            user_id=user.id,
            reward_id=reward_id,
            idempotency_key=payload.idempotency_key,
            destination=payload.destination,
        )
    except RewardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return {
        "redemption": _redemption_out(db, rd, owner=True),
        "balance": db.get(User, user.id).points,
    }


@router.post("/redemptions/{redemption_id}/cancel")
def cancel_redemption(
    redemption_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rd = db.get(RewardRedemption, redemption_id)
    if rd is None or rd.user_id != user.id:
        raise HTTPException(status_code=404, detail="Redemption not found.")
    try:
        user_cancel_available(db, rd)
    except RewardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return {
        "redemption": _redemption_out(db, rd, owner=True),
        "balance": db.get(User, user.id).points,
    }
