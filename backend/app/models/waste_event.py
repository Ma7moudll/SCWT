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


class WasteEvent(Base):
    __tablename__ = "waste_events"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_waste_operation_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    station_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False
    )
    deposit_session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("deposit_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    ai_prediction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_predictions.id", ondelete="RESTRICT"), nullable=False
    )
    predicted_class: Mapped[str] = mapped_column(String(32), nullable=False)
    actual_position: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_grams: Mapped[float] = mapped_column(Float, nullable=False)
    mechanical_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="confirmed")  # confirmed|rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )