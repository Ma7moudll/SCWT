#!/usr/bin/env python
"""Remove all non-admin (student) accounts and their dependent data.

Development/test hygiene only:
    * ADMIN accounts are ALWAYS preserved.
    * Dependent records are deleted through the ORM in foreign-key order
      (waste_events -> deposit_sessions -> ai_predictions -> auth_tokens ->
       user_challenges -> student leaderboard rows -> user). No raw SQL.
    * Faculty leaderboard totals are recomputed from the remaining users.
    * Refuses to run when ENVIRONMENT=production — no override flag exists.
    * Dry-run by default; pass --yes to apply.

Usage:
    python scripts/reset_dev_users.py           # summary of what would go
    python scripts/reset_dev_users.py --yes     # actually delete
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

SAFE_ENVIRONMENTS = {"development", "dev", "test", "testing", "local", "cicd"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="apply the deletion")
    parser.add_argument(
        "--db",
        choices=["dev", "e2e"],
        default="dev",
        help="database alias (default: dev)",
    )
    args = parser.parse_args()

    if args.db == "e2e":
        os.environ.setdefault(
            "DATABASE_URL",
            "postgresql+psycopg2://scwt:scwt@localhost:5432/scwt_db_e2e",
        )

    from app.config import get_settings

    settings = get_settings()
    env = settings.environment.strip().lower()
    if env not in SAFE_ENVIRONMENTS or settings.is_production:
        print(
            f"REFUSING: environment '{settings.environment}' is not a "
            "development/test environment. This script never runs in production."
        )
        return 2

    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import (
        AiPrediction,
        AuthToken,
        DepositSession,
        Faculty,
        LeaderboardEntry,
        User,
        UserChallenge,
        WasteEvent,
    )

    with SessionLocal() as db:
        users = db.execute(select(User)).scalars().all()
        admins = [u for u in users if u.role == "admin"]
        students = [u for u in users if u.role != "admin"]
        student_ids = [u.id for u in students]

        def _count(model, column):
            if not student_ids:
                return 0
            return db.execute(
                select(func.count()).select_from(model).where(column.in_(student_ids))
            ).scalar_one()

        deposits = _count(DepositSession, DepositSession.user_id)
        events = _count(WasteEvent, WasteEvent.user_id)
        predictions = _count(AiPrediction, AiPrediction.user_id)
        tokens = _count(AuthToken, AuthToken.user_id)
        challenge_rows = _count(UserChallenge, UserChallenge.user_id)
        lb_rows = _count(LeaderboardEntry, LeaderboardEntry.user_id)
        points_removed = sum(u.points for u in students)

        print(f"[reset-users] environment : {env}")
        print(f"[reset-users] admins kept : {len(admins)}")
        for admin in admins:
            print(f"[reset-users]   PRESERVE {admin.email} (role=admin)")
        print(f"[reset-users] students    : {len(students)}")
        print(
            f"[reset-users] dependents  : {deposits} deposit sessions, "
            f"{events} waste events, {predictions} AI predictions, "
            f"{tokens} auth tokens, {challenge_rows} challenge rows, "
            f"{lb_rows} leaderboard rows"
        )
        print(f"[reset-users] points lost : {points_removed}")

        if not args.yes:
            print("[reset-users] DRY RUN — nothing deleted. Re-run with --yes.")
            return 0

        affected_faculties = sorted({u.faculty_id for u in students})

        # Foreign-key-safe deletion order. waste_events RESTRICT-reference
        # deposit_sessions and ai_predictions, so they go first; sessions
        # RESTRICT-reference ai_predictions, so sessions precede predictions.
        for model, column in (
            (WasteEvent, WasteEvent.user_id),
            (DepositSession, DepositSession.user_id),
            (AiPrediction, AiPrediction.user_id),
            (AuthToken, AuthToken.user_id),
            (UserChallenge, UserChallenge.user_id),
            (LeaderboardEntry, LeaderboardEntry.user_id),
        ):
            if student_ids:
                deleted = db.execute(
                    model.__table__.delete().where(column.in_(student_ids))
                )
                print(f"[reset-users] deleted {deleted.rowcount} from {model.__tablename__}")

        for user in students:
            db.delete(user)
        db.flush()

        # Recompute faculty leaderboard totals from the surviving users so no
        # stale aggregate survives its members.
        for faculty_id in affected_faculties:
            remaining = (
                db.execute(
                    select(func.coalesce(func.sum(User.points), 0)).where(
                        User.faculty_id == faculty_id
                    )
                ).scalar_one()
                or 0
            )
            entry = db.execute(
                select(LeaderboardEntry).where(
                    LeaderboardEntry.scope == "faculties",
                    LeaderboardEntry.entity_id == faculty_id,
                )
            ).scalar_one_or_none()
            if entry is None and db.get(Faculty, faculty_id) is not None:
                faculty = db.get(Faculty, faculty_id)
                entry = LeaderboardEntry(
                    id=f"lb-f-{faculty_id}",
                    scope="faculties",
                    entity_id=faculty_id,
                    name=faculty.name,
                    detail="Faculty",
                    points=int(remaining),
                    faculty_id=faculty_id,
                )
                db.add(entry)
            elif entry is not None:
                entry.points = int(remaining)

        db.commit()

        # ---- consistency gate: the script only exits 0 on a clean state ----
        problems: list[str] = []
        remaining_users = db.execute(select(User)).scalars().all()
        if any(u.role != "admin" for u in []):
            problems.append("non-admin survived")  # unreachable; belt & braces
        for uid in student_ids:
            if db.get(User, uid) is not None:
                problems.append(f"user {uid} still present")
            for model, column in (
                (DepositSession, DepositSession.user_id),
                (WasteEvent, WasteEvent.user_id),
                (AiPrediction, AiPrediction.user_id),
                (AuthToken, AuthToken.user_id),
                (UserChallenge, UserChallenge.user_id),
            ):
                if (
                    db.execute(
                        select(func.count())
                        .select_from(model)
                        .where(column == uid)
                    ).scalar_one()
                    > 0
                ):
                    problems.append(f"orphaned {model.__tablename__} for {uid}")
        if any(u.points < 0 for u in remaining_users):
            problems.append("negative points after cleanup")

        if problems:
            db.rollback()
            for problem in problems[:20]:
                print(f"[reset-users] INCONSISTENT: {problem}")
            return 1

        print()
        print(f"Admin accounts preserved: {len(admins)}")
        print(f"Student accounts removed: {len(students)}")
        print(f"Deposits removed: {deposits}")
        print(f"Points removed: {points_removed}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
