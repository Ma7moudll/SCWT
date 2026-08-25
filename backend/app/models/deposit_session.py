from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class DepositSession(Base):
    """One physical deposit attempt. `operation_id` is globally unique and the
    same operation can never award points twice (UNIQUE enforced here and on
    waste_events.operation_id)."""

    __tablename__ = "deposit_sessions"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_deposit_operation_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    station_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False
    )
    ai_prediction_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ai_predictions.id", ondelete="RESTRICT"), nullable=True
    )
    routing_policy_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("routing_policies.id", ondelete="RESTRICT"), nullable=True
    )
    potential_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # capture|analyzing|pending|confirmed|rejected|cancelled|expired
    expected_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(16), nullable=True)  # high|medium|low
    actual_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_stable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mechanical_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)