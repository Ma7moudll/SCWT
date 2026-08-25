from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Reward(Base):
    """A catalog item students can exchange points for.

    Categories: cash (Vodafone Cash / InstaPay), food, printing, discount.
    Cash rewards only ever create a PENDING redemption for an admin to
    fulfill — nothing here pretends money moved.
    """

    __tablename__ = "rewards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    category: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    value_label: Mapped[str] = mapped_column(String(64), nullable=False)
    value_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EGP")
    icon: Mapped[str] = mapped_column(String(32), nullable=False, default="card_giftcard")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_destination: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RewardRedemption(Base):
    """One redemption = one atomic points deduction. See reward_service."""

    __tablename__ = "reward_redemptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reward_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rewards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    points_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    redemption_code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True)
    destination: Mapped[str | None] = mapped_column(String(128), nullable=True)
    admin_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- status vocabulary -------------------------------------------------
    # cash flow   : pending -> approved -> fulfilled | rejected
    # code flow   : available -> used
    # both        : cancelled (user-initiated before fulfillment)
