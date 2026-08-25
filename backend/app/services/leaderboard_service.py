from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Faculty, LeaderboardEntry, User


class LeaderboardService:
    def get_entries(self, db: Session, scope: str) -> list[dict]:
        rows = db.execute(
            select(LeaderboardEntry)
            .where(LeaderboardEntry.scope == scope)
            .order_by(LeaderboardEntry.points.desc())
            .limit(50)
        ).scalars().all()
        return [
            {"id": r.entity_id, "name": r.name, "detail": r.detail, "points": r.points}
            for r in rows
        ]

    def get_entries_paged(
        self, db: Session, scope: str, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        """Ranked page + total for the scope."""
        from sqlalchemy import func as sa_func

        base = select(LeaderboardEntry).where(LeaderboardEntry.scope == scope)
        total = db.execute(
            select(sa_func.count()).select_from(base.subquery())
        ).scalar_one()
        rows = db.execute(
            base.order_by(LeaderboardEntry.points.desc()).limit(limit).offset(offset)
        ).scalars().all()
        entries = [
            {"id": r.entity_id, "name": r.name, "detail": r.detail, "points": r.points}
            for r in rows
        ]
        return entries, int(total)

    def repair(self, db: Session) -> None:
        """Rebuild ranking rows from ground truth. Called at startup after a
        seed so rankings are never stale."""
        for entry in db.execute(
            select(LeaderboardEntry).where(LeaderboardEntry.scope == "students")
        ).scalars():
            db.delete(entry)

        for user in db.execute(select(User)).scalars():
            db.add(self._student_entry(db, user))

        for faculty in db.execute(select(Faculty)).scalars():
            total = sum(
                u.points
                for u in db.execute(select(User).where(User.faculty_id == faculty.id)).scalars()
            )
            entry = db.execute(
                select(LeaderboardEntry).where(
                    LeaderboardEntry.scope == "faculties",
                    LeaderboardEntry.entity_id == faculty.id,
                )
            ).scalar_one_or_none()
            if entry is None:
                db.add(
                    LeaderboardEntry(
                        id=f"lb-f-{faculty.id}",
                        scope="faculties",
                        entity_id=faculty.id,
                        name=faculty.name,
                        detail="Faculty",
                        points=total,
                        faculty_id=faculty.id,
                    )
                )
            else:
                entry.points = total
        db.commit()

    def _student_entry(self, db: Session, user: User) -> LeaderboardEntry:
        faculty = db.get(Faculty, user.faculty_id)
        detail = faculty.name if faculty else ""
        return LeaderboardEntry(
            id=f"lb-u-{user.id}",
            scope="students",
            entity_id=user.id,
            name=user.name,
            detail=detail,
            points=user.points,
            user_id=user.id,
        )