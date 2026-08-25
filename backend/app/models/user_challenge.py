"""Per-user challenge completion.

`Challenge.completed` is a legacy global flag; real completion is per user.
A row here is created EXACTLY ONCE when a validated deposit pushes the user's
confirmed tonnage for the challenge waste class past `target_kg`, and the
reward is awarded in the same transaction. The unique constraint on
(user_id, challenge_id) makes duplicate rewards impossible at the schema
level, not just logically.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class UserChallenge(Base):
    __tablename__ = "user_challenges"
    __table_args__ = (
        UniqueConstraint("user_id", "challenge_id", name="uq_user_challenge"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False, index=True
    )
    challenge_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("challenges.id"), nullable=False, index=True
    )
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @staticmethod
    def new_id() -> str:
        return f"uc-{uuid.uuid4().hex[:20]}"
