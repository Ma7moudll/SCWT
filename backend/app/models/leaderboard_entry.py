from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LeaderboardEntry(Base):
    """Materialized ranking rows: one per student (scope=students) and one per
    faculty (scope=faculties). Kept in sync inside the points transaction."""

    __tablename__ = "leaderboard_entries"
    __table_args__ = (
        UniqueConstraint("scope", "entity_id", name="uq_leaderboard_scope_entity"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # students|faculties
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    detail: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    faculty_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("faculties.id", ondelete="CASCADE"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )