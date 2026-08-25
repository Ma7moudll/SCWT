from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    def get_by_email(self, db: Session, email: str) -> User | None:
        return db.execute(select(User).where(User.email == email.lower().strip())).scalar_one_or_none()

    def get_by_student_code(self, db: Session, code: str) -> User | None:
        return db.execute(select(User).where(User.student_code == code)).scalar_one_or_none()