from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    student_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    faculty_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("faculties.id", ondelete="RESTRICT"), nullable=False
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # "student" | "admin" — admin gates station/user/challenge management.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="student")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Bumped on password change/reset; JWTs carry `ver` and older generations
    # are refused (see security.deps). Invalidates every outstanding token.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Profile photo generation counter: 0 = no photo; bumped on every upload
    # or removal so clients can cache-bust the avatar URL.
    avatar_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )