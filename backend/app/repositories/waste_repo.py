from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import WasteEvent
from .base import BaseRepository


class WasteRepository(BaseRepository[WasteEvent]):
    model = WasteEvent

    def list_by_user(self, db: Session, user_id: str, limit: int = 100) -> list[WasteEvent]:
        # Full audit trail: confirmed + rejected (rejected rows carry
        # points_awarded == 0 so the client can still render the attempt).
        rows = db.execute(
            select(WasteEvent)
            .where(WasteEvent.user_id == user_id)
            .order_by(WasteEvent.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return list(rows)

    def list_by_user_paged(
        self, db: Session, user_id: str, limit: int, offset: int
    ) -> tuple[list[WasteEvent], int]:
        """Ordered page + total count (same audit-trail filter)."""
        base = select(WasteEvent).where(WasteEvent.user_id == user_id)
        total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
        rows = db.execute(
            base.order_by(WasteEvent.created_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
        return list(rows), int(total)

    def get_by_operation_id(self, db: Session, operation_id: str) -> WasteEvent | None:
        return db.execute(
            select(WasteEvent).where(WasteEvent.operation_id == operation_id)
        ).scalar_one_or_none()

    def events_after(self, db: Session, user_id: str, after: datetime) -> list[WasteEvent]:
        rows = db.execute(
            select(WasteEvent).where(
                WasteEvent.user_id == user_id,
                WasteEvent.status == "confirmed",
                WasteEvent.created_at >= after,
            )
        ).scalars().all()
        return list(rows)