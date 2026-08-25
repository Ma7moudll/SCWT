from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AiPrediction(Base):
    __tablename__ = "ai_predictions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    operation_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    predicted_class: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(16), nullable=False)  # high|medium|low
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")  # ai|demo
    routing_policy_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("routing_policies.id", ondelete="RESTRICT"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)