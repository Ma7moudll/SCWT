from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from ..database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model: type[T]

    def get(self, db: Session, id: str) -> T | None:
        return db.get(self.model, id)