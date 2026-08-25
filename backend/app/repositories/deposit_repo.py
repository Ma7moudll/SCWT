from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DepositSession
from .base import BaseRepository


class DepositRepository(BaseRepository[DepositSession]):
    model = DepositSession

    def get_by_operation_id(self, db: Session, operation_id: str) -> DepositSession | None:
        return db.execute(
            select(DepositSession).where(DepositSession.operation_id == operation_id)
        ).scalar_one_or_none()