from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Faculty, OperationCounter, RoutingPolicy, User
from ..security.password import hash_password

DATE_FMT = "%Y%m%d"  # compact datetime for OP-YYYYMMDD-NNNNNN ids


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _day(date: datetime) -> str:
    return date.strftime(DATE_FMT)


def next_operation_id(db: Session, at: datetime | None = None) -> str:
    """Mints `OP-YYYYMMDD-NNNNNN` inside the current transaction. The counter
    row is locked (PostgreSQL) so concurrent minting cannot collide; SQLite
    tests are serialized so the lock is a no-op but still correct."""
    now = at or utcnow()
    day = _day(now)
    counter = db.query(OperationCounter).filter(OperationCounter.day == day).with_for_update().first()
    if counter is None:
        counter = OperationCounter(day=day, value=0)
        db.add(counter)
    counter.value += 1
    db.flush()
    return f"OP-{day}-{counter.value:06d}"


class SeedError(RuntimeError):
    pass


def seed(db: Session, seed_demo_user: bool = False) -> None:
    """Idempotent development seed.

    Always creates the configuration the runtime needs: faculties, the station,
    the routing policy and the operation counter. When `seed_demo_user` is
    True it ALSO creates the well-known dev/test account
    (`demo@ecolamp.campus` / `demo123`). Runtime stacks leave that OFF so no
    demo users exist in the real database; test suites and the software E2E
    opt in so their fixtures keep working.
    """
    from ..models import Station

    # Each block is independently idempotent so partial databases (e.g. one
    # reset with the config seed, then booted with SEED_DEMO_USER=true) still
    # converge to the full dev state.
    if db.query(Faculty).first() is None:
        db.add_all(
            [
                Faculty(id="ENGINEERING", name="Engineering"),
                Faculty(id="PHYSICAL_THERAPY", name="Physical Therapy"),
                Faculty(id="ART_DESIGN", name="Art & Design"),
            ]
        )
        db.flush()

        db.add_all(
            [
                Station(
                    id="st-001",
                    station_code="ST-001",
                    name="Ecolamp Engineering Station",
                    status="offline",
                )
            ]
        )

        routing = [
            ("plastic", 1, 5),
            ("metal", 2, 10),
            ("paper", 3, 5),
            ("other", 4, 0),
        ]
        db.add_all(
            [
                RoutingPolicy(
                    id=f"routing-{cls}", waste_class=cls, position=pos, potential_points=pts
                )
                for cls, pos, pts in routing
            ]
        )

    if seed_demo_user and db.query(User).filter(User.id == "u-demo").first() is None:
        db.add(
            User(
                id="u-demo",
                email="demo@ecolamp.campus",
                student_code="S-DEMO1",
                name="Demo Student",
                password_hash=hash_password("demo123"),
                faculty_id="ENGINEERING",
                points=45,
            )
        )

    today = _day(utcnow())
    if db.query(OperationCounter).filter(OperationCounter.day == today).first() is None:
        db.add(
            OperationCounter(day=today, value=0)
        )

    _seed_reward_catalog(db)
    db.commit()


def _seed_reward_catalog(db: Session) -> None:
    """Idempotent starter catalog — the four reward products the program
    actually offers. Admins edit/deactivate them from the panel; seeding
    only inserts what is missing and never resurrects deleted rows."""
    from ..models import Reward

    catalog = [
        dict(
            id="rw-vodafone-10",
            category="cash",
            name="Vodafone Cash 10 EGP",
            description="10 EGP transferred to your Vodafone Cash wallet by the admin team.",
            provider="Vodafone Cash",
            points_cost=100,
            value_label="10 EGP",
            value_amount=10.0,
            icon="phone_android",
            requires_destination=True,
        ),
        dict(
            id="rw-instapay-25",
            category="cash",
            name="InstaPay Transfer 25 EGP",
            description="25 EGP sent to your InstaPay handle (bank account or wallet).",
            provider="InstaPay",
            points_cost=250,
            value_label="25 EGP",
            value_amount=25.0,
            icon="account_balance",
            requires_destination=True,
        ),
        dict(
            id="rw-mix-coffee-20",
            category="food",
            name="MIX Coffee 20% Off",
            description="20% off any drink at the MIX Coffee campus branch.",
            provider="MIX Coffee",
            points_cost=60,
            value_label="20% OFF",
            value_amount=0.20,
            icon="local_cafe",
        ),
        dict(
            id="rw-copy-center-30",
            category="printing",
            name="Copy Center 30 Pages",
            description="30 black-and-white pages printed free at the campus copy center.",
            provider="Campus Copy Center",
            points_cost=80,
            value_label="30 pages",
            value_amount=30.0,
            icon="print",
        ),
    ]
    for row in catalog:
        if db.get(Reward, row["id"]) is None:
            db.add(Reward(**row))


def seed_faculty_leaderboard(db: Session) -> None:
    from ..models import LeaderboardEntry

    for faculty in db.query(Faculty).all():
        entry = (
            db.query(LeaderboardEntry)
            .filter(LeaderboardEntry.scope == "faculties", LeaderboardEntry.entity_id == faculty.id)
            .first()
        )
        if entry is None:
            db.add(
                LeaderboardEntry(
                    id=f"lb-f-{faculty.id}",
                    scope="faculties",
                    entity_id=faculty.id,
                    name=faculty.name,
                    detail="Faculty",
                    points=0,
                    faculty_id=faculty.id,
                )
            )
    db.commit()