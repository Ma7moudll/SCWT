"""The atomic points transaction.

Nothing outside this module (and the services that call it) may change a
user's point balance. Awarding happens in a single DB transaction:

    BEGIN
        insert waste_event
        update user points
        upsert leaderboard entries (student + faculty)
        mark deposit session completed
    COMMIT

Any failure rolls the whole thing back so no operation ever double-spends.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DepositSession, LeaderboardEntry, User, WasteEvent


def award_points(
    db: Session,
    session: DepositSession,
    *,
    actual_position: int,
    weight_grams: float,
    weight_stable: bool,
    mechanical_confirmed: bool,
    points_awarded: int,
) -> WasteEvent:
    user = db.get(User, session.user_id)
    if user is None:
        raise ValueError("deposit user no longer exists")

    event = WasteEvent(
        id=f"waste-{session.operation_id}",
        operation_id=session.operation_id,
        user_id=user.id,
        station_id=session.station_id,
        deposit_session_id=session.id,
        ai_prediction_id=session.ai_prediction_id,
        predicted_class=session.expected_class,
        actual_position=actual_position,
        weight_grams=weight_grams,
        mechanical_confirmed=mechanical_confirmed,
        points_awarded=points_awarded,
        status="confirmed",
    )
    db.add(event)

    old_points = user.points
    user.points = old_points + points_awarded

    session.actual_position = actual_position
    session.weight_grams = weight_grams
    session.weight_stable = weight_stable
    session.mechanical_confirmed = mechanical_confirmed
    session.status = "confirmed"
    session.completed_at = datetime.now(timezone.utc)

    _upsert_student_leaderboard(db, user)
    _upsert_faculty_leaderboard(db, user.faculty_id, user.points)

    db.flush()
    return event


def record_rejection(
    db: Session,
    session: DepositSession,
    *,
    actual_position: int | None,
    weight_grams: float | None,
    reason: str,
    points_awarded: int = 0,
    session_status: str = "rejected",
) -> WasteEvent:
    """Persists an auditable rejected waste event (0 points) and closes the
    session. Still one row per operation — protects the audit trail without
    ever touching the user's point balance."""
    event = WasteEvent(
        id=f"waste-rej-{session.operation_id}",
        operation_id=session.operation_id,
        user_id=session.user_id,
        station_id=session.station_id,
        deposit_session_id=session.id,
        ai_prediction_id=session.ai_prediction_id,
        predicted_class=session.expected_class,
        actual_position=actual_position if actual_position is not None else 0,
        weight_grams=weight_grams if weight_grams is not None else 0.0,
        mechanical_confirmed=False,
        points_awarded=points_awarded,
        status="rejected",
    )
    db.add(event)

    session.actual_position = actual_position
    session.weight_grams = weight_grams
    session.status = session_status
    session.reject_reason = reason
    session.completed_at = datetime.now(timezone.utc)
    db.flush()
    return event


def _upsert_student_leaderboard(db: Session, user: User) -> None:
    entry = db.execute(
        select(LeaderboardEntry).where(
            LeaderboardEntry.scope == "students", LeaderboardEntry.entity_id == user.id
        )
    ).scalar_one_or_none()
    if entry is None:
        db.add(
            LeaderboardEntry(
                id=f"lb-u-{user.id}",
                scope="students",
                entity_id=user.id,
                name=user.name,
                detail=_faculty_name(db, user.faculty_id),
                points=user.points,
                user_id=user.id,
            )
        )
    else:
        entry.points = user.points


def _upsert_faculty_leaderboard(db: Session, faculty_id: str, _points: int) -> None:
    from ..models import Faculty

    # Flush pending user-point changes before aggregating so the faculty total
    # reflects the just-awarded points (autoflush is off).
    db.flush()
    faculty = db.get(Faculty, faculty_id)
    if faculty is None:
        return
    total = db.execute(
        select(User).where(User.faculty_id == faculty_id)
    ).scalars().all()
    faculty_total = sum(u.points for u in total)
    entry = db.execute(
        select(LeaderboardEntry).where(
            LeaderboardEntry.scope == "faculties", LeaderboardEntry.entity_id == faculty_id
        )
    ).scalar_one_or_none()
    if entry is None:
        db.add(
            LeaderboardEntry(
                id=f"lb-f-{faculty_id}",
                scope="faculties",
                entity_id=faculty_id,
                name=faculty.name,
                detail="Faculty",
                points=faculty_total,
                faculty_id=faculty_id,
            )
        )
    else:
        entry.points = faculty_total


def _faculty_name(db: Session, faculty_id: str) -> str:
    from ..models import Faculty

    faculty = db.get(Faculty, faculty_id)
    return faculty.name if faculty else ""