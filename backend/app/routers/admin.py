"""Admin management endpoints — every route requires `role == "admin"`.

Foundation only (no panel): station lifecycle, user moderation, challenge
management. Unrestricted exposure is exactly what this router prevents.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import delete as sa_delete, func as sa_func, select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuthToken, Challenge, DepositSession, Faculty, Reward, RewardRedemption, Station, User, UserChallenge
from ..security import require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# -- stations ------------------------------------------------------------------


class StationUpsert(BaseModel):
    station_code: str
    name: str
    enabled: bool = True


class StationPatch(BaseModel):
    name: str | None = None
    enabled: bool | None = None


@router.post("/stations")
def create_station(payload: StationUpsert, db: Session = Depends(get_db)) -> dict:
    existing = (
        db.execute(select(Station).where(Station.station_code == payload.station_code))
        .scalars()
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A station with this code already exists.")
    station = Station(
        id=f"st-{uuid.uuid4().hex[:8]}",
        station_code=payload.station_code,
        name=payload.name,
        status="online" if payload.enabled else "disabled",
    )
    db.add(station)
    db.commit()
    db.refresh(station)
    return {"id": station.id, "station_code": station.station_code, "status": station.status}


@router.patch("/stations/{station_id}")
def patch_station(
    station_id: str, payload: StationPatch, db: Session = Depends(get_db)
) -> dict:
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="This station could not be found.")
    if payload.name is not None:
        station.name = payload.name
    if payload.enabled is not None:
        station.status = "online" if payload.enabled else "disabled"
    db.commit()
    return {
        "id": station.id,
        "station_code": station.station_code,
        "name": station.name,
        "status": station.status,
    }


@router.delete("/stations/{station_id}")
def delete_station(station_id: str, db: Session = Depends(get_db)) -> dict:
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="This station could not be found.")
    used = (
        db.execute(select(sa_func.count()).select_from(DepositSession).where(DepositSession.station_id == station_id))
        .scalar_one()
    )
    if int(used) > 0:
        raise HTTPException(
            status_code=409,
            detail="Station has deposit history — disable it instead of deleting.",
        )
    db.delete(station)
    db.commit()
    return {"deleted": station_id}


# -- users -------------------------------------------------------------------


class UserPatch(BaseModel):
    is_active: bool | None = None
    name: str | None = None
    faculty_id: str | None = None
    points: int | None = None
    role: str | None = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str | None) -> str | None:
        if v is not None and v not in ("student", "admin"):
            raise ValueError("role must be 'student' or 'admin'")
        return v

    @field_validator("points")
    @classmethod
    def _non_negative_points(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("points cannot be negative")
        return v


@router.get("/users")
def list_users(
    q: str = Query("", max_length=128),
    faculty: str = Query("", max_length=64),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Student directory: search by name/email/student code, filter by faculty,
    paged. Read-only — moderation actions go through PATCH /users/{id}."""
    from sqlalchemy import func as sa_func

    from .auth import faculty_name

    base = select(User)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(
            sa_func.lower(User.name).like(like)
            | sa_func.lower(User.email).like(like)
            | sa_func.lower(User.student_code).like(like)
        )
    if faculty:
        base = base.where(User.faculty_id == faculty)

    total = db.execute(select(sa_func.count()).select_from(base.subquery())).scalar_one()
    users = (
        db.execute(base.order_by(User.created_at.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "student_code": u.student_code,
                "faculty_id": u.faculty_id,
                "faculty_name": faculty_name(db, u.faculty_id),
                "role": u.role,
                "is_active": u.is_active,
                "points": u.points,
            }
            for u in users
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    payload: UserPatch,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="This account could not be found.")
    if payload.is_active is not None:
        if not payload.is_active and user.id == admin.id:
            raise HTTPException(status_code=422, detail="You cannot deactivate your own account.")
        user.is_active = payload.is_active
    if payload.name is not None and payload.name.strip():
        user.name = payload.name.strip()
    if payload.faculty_id is not None:
        from ..models import Faculty
        if db.get(Faculty, payload.faculty_id) is None:
            raise HTTPException(status_code=404, detail="Faculty not found.")
        user.faculty_id = payload.faculty_id
    if payload.points is not None:
        user.points = payload.points
    if payload.role is not None and payload.role != user.role:
        if user.id == admin.id and payload.role != "admin":
            raise HTTPException(status_code=422, detail="You cannot demote your own account.")
        admins = (
            db.execute(select(sa_func.count()).select_from(User).where(User.role == "admin"))
            .scalar_one()
        )
        if user.role == "admin" and int(admins) <= 1:
            raise HTTPException(status_code=409, detail="This is the only administrator.")
        user.role = payload.role
    db.commit()
    return {"id": user.id, "is_active": user.is_active, "name": user.name,
            "faculty_id": user.faculty_id, "points": user.points, "role": user.role}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Hard-delete ONLY when the account has no history; otherwise deactivate."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="This account could not be found.")
    if user.id == admin.id:
        raise HTTPException(status_code=422, detail="You cannot delete your own account.")
    deposits = (
        db.execute(select(sa_func.count()).select_from(DepositSession).where(DepositSession.user_id == user_id))
        .scalar_one()
    )
    redemptions = (
        db.execute(select(sa_func.count()).select_from(RewardRedemption).where(RewardRedemption.user_id == user_id))
        .scalar_one()
    )
    if int(deposits) > 0 or int(redemptions) > 0:
        raise HTTPException(
            status_code=409,
            detail="Account has deposit/redemption history — deactivate it instead.",
        )
    for t in (AuthToken, UserChallenge):
        db.query(t).filter(t.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {"deleted": user_id}


# -- challenges -----------------------------------------------------------------


class ChallengeCreate(BaseModel):
    id: str | None = None  # server-generated when absent
    title: str
    description: str
    theme_emoji: str = "♻️"
    waste_class: str
    target_kg: float
    reward_points: int = 0


class ChallengePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    theme_emoji: str | None = None
    waste_class: str | None = None
    target_kg: float | None = None
    reward_points: int | None = None
    active: bool | None = None

    @field_validator("target_kg")
    @classmethod
    def _positive_target(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("target_kg must be positive")
        return v


@router.post("/challenges")
def create_challenge(payload: ChallengeCreate, db: Session = Depends(get_db)) -> dict:
    challenge_id = payload.id or f"ch-{uuid.uuid4().hex[:12]}"
    if db.get(Challenge, challenge_id) is not None:
        raise HTTPException(status_code=409, detail="A challenge with this ID already exists.")
    challenge = Challenge(
        id=challenge_id,
        title=payload.title,
        description=payload.description,
        theme_emoji=payload.theme_emoji,
        waste_class=payload.waste_class,
        target_kg=payload.target_kg,
        reward_points=payload.reward_points,
    )
    db.add(challenge)
    db.commit()
    return {"id": challenge.id, "title": challenge.title}


@router.patch("/challenges/{challenge_id}")
def patch_challenge(
    challenge_id: str, payload: ChallengePatch, db: Session = Depends(get_db)
) -> dict:
    challenge = db.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="This challenge could not be found.")
    for field in ("title", "description", "theme_emoji", "waste_class",
                  "target_kg", "reward_points", "active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(challenge, field, value)
    db.commit()
    return {"id": challenge.id, "title": challenge.title, "active": challenge.active}


@router.delete("/challenges/{challenge_id}")
def delete_challenge(challenge_id: str, db: Session = Depends(get_db)) -> dict:
    challenge = db.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="This challenge could not be found.")
    joined = (
        db.execute(select(sa_func.count()).select_from(UserChallenge).where(UserChallenge.challenge_id == challenge_id))
        .scalar_one()
    )
    if int(joined) > 0:
        raise HTTPException(
            status_code=409,
            detail="Students already joined this challenge — deactivate it instead.",
        )
    db.delete(challenge)
    db.commit()
    return {"deleted": challenge_id}


@router.get("/challenges")
def list_challenges_admin(
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    challenges = (
        db.execute(select(Challenge).order_by(Challenge.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "theme_emoji": c.theme_emoji,
                "waste_class": c.waste_class,
                "target_kg": c.target_kg,
                "reward_points": c.reward_points,
                "active": bool(c.active),
            }
            for c in challenges
        ]
    }


# -- dashboard analytics ---------------------------------------------------------
# Read-only aggregates backing the admin web console. Every route inherits the
# router-level require_admin dependency.


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    from datetime import datetime, timezone

    from sqlalchemy import func

    from ..models import WasteEvent

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def _scalar(stmt) -> float:
        return float(db.execute(stmt).scalar() or 0)

    students = db.execute(select(func.count()).select_from(User)).scalar_one()
    deposits = db.execute(
        select(func.count()).select_from(WasteEvent).where(WasteEvent.status == "confirmed")
    ).scalar_one()
    weight_g = _scalar(
        select(func.coalesce(func.sum(WasteEvent.weight_grams), 0.0)).where(
            WasteEvent.status == "confirmed"
        )
    )
    points = int(_scalar(
        select(func.coalesce(func.sum(WasteEvent.points_awarded), 0)).where(
            WasteEvent.status == "confirmed"
        )
    ))
    today_events = db.execute(
        select(func.count())
        .select_from(WasteEvent)
        .where(WasteEvent.created_at >= day_start)
    ).scalar_one()
    stations = db.execute(select(Station)).scalars().all()
    active = sum(1 for s in stations if s.status == "online")
    offline = sum(1 for s in stations if s.status != "online")
    return {
        "total_students": int(students),
        "total_deposits": int(deposits),
        "recycled_kg": round(weight_g / 1000.0, 2),
        # Documented placeholder factor (see ImpactService.CO2_PER_KG).
        "co2_saved_kg": round(weight_g / 1000.0 * 0.5, 2),
        "points_awarded": points,
        "active_stations": active,
        "offline_stations": offline,
        "today_activity": int(today_events),
    }


@router.get("/faculties")
def faculty_stats(db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import func

    from ..models import Faculty, WasteEvent

    faculties = db.execute(select(Faculty).order_by(Faculty.id)).scalars().all()
    items = []
    for f in faculties:
        users = db.execute(select(User).where(User.faculty_id == f.id)).scalars().all()
        user_ids = [u.id for u in users]
        weight_g = 0.0
        items_recycled = 0
        if user_ids:
            row = db.execute(
                select(
                    func.coalesce(func.sum(WasteEvent.weight_grams), 0.0),
                    func.count(WasteEvent.id),
                ).where(
                    WasteEvent.user_id.in_(user_ids), WasteEvent.status == "confirmed"
                )
            ).one()
            weight_g = float(row[0] or 0.0)
            items_recycled = int(row[1] or 0)
        items.append(
            {
                "id": f.id,
                "name": f.name,
                "students": len(users),
                "points": sum(u.points for u in users),
                "recycled_kg": round(weight_g / 1000.0, 2),
                "items": items_recycled,
            }
        )
    items.sort(key=lambda x: x["points"], reverse=True)
    for rank, entry in enumerate(items, start=1):
        entry["rank"] = rank
    return {"items": items}


class FacultyCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not 2 <= len(v) <= 128:
            raise ValueError("Faculty name must be 2-128 characters.")
        return v


class FacultyRename(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not 2 <= len(v) <= 128:
            raise ValueError("Faculty name must be 2-128 characters.")
        return v


def _faculty_slug(db: Session, name: str) -> str:
    """Stable uppercase-underscore id derived from the name (ENGINEERING
    style), suffixed on collision."""
    base = "".join(ch if ch.isalnum() else "_" for ch in name.upper())
    base = "_".join(part for part in base.split("_") if part) or "FACULTY"
    candidate = base[:60]
    suffix = 2
    while db.get(Faculty, candidate) is not None:
        candidate = f"{base[:56]}-{suffix}"
        suffix += 1
    return candidate


@router.post("/faculties")
def create_faculty(payload: FacultyCreate, db: Session = Depends(get_db)) -> dict:
    existing = db.execute(
        select(Faculty).where(Faculty.name == payload.name)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A faculty with this name already exists.")
    faculty = Faculty(id=_faculty_slug(db, payload.name), name=payload.name)
    db.add(faculty)
    db.commit()
    db.refresh(faculty)
    return {"id": faculty.id, "name": faculty.name}


@router.patch("/faculties/{faculty_id}")
def rename_faculty(
    faculty_id: str, payload: FacultyRename, db: Session = Depends(get_db)
) -> dict:
    faculty = db.get(Faculty, faculty_id)
    if faculty is None:
        raise HTTPException(status_code=404, detail="This faculty could not be found.")
    clash = db.execute(
        select(Faculty).where(Faculty.name == payload.name, Faculty.id != faculty_id)
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(status_code=409, detail="A faculty with this name already exists.")
    faculty.name = payload.name
    # The faculty leaderboard row carries the display name.
    from ..models import LeaderboardEntry

    lb = db.execute(
        select(LeaderboardEntry).where(
            LeaderboardEntry.scope == "faculties",
            LeaderboardEntry.entity_id == faculty_id,
        )
    ).scalar_one_or_none()
    if lb is not None:
        lb.name = payload.name
    db.commit()
    return {"id": faculty.id, "name": faculty.name}


@router.delete("/faculties/{faculty_id}")
def delete_faculty(faculty_id: str, db: Session = Depends(get_db)) -> dict:
    faculty = db.get(Faculty, faculty_id)
    if faculty is None:
        raise HTTPException(status_code=404, detail="This faculty could not be found.")
    enrolled = (
        db.execute(select(sa_func.count()).select_from(User).where(User.faculty_id == faculty_id))
        .scalar_one()
    )
    if int(enrolled) > 0:
        raise HTTPException(
            status_code=409,
            detail="Faculty still has students — move them to another faculty first.",
        )
    from ..models import LeaderboardEntry

    db.execute(
        sa_delete(LeaderboardEntry).where(
            LeaderboardEntry.scope == "faculties",
            LeaderboardEntry.entity_id == faculty_id,
        )
    )
    db.delete(faculty)
    db.commit()
    return {"deleted": faculty_id}


@router.get("/stations")
def list_stations(db: Session = Depends(get_db)) -> dict:
    from ..services.station_registry import registry

    stations = db.execute(select(Station).order_by(Station.station_code)).scalars().all()
    out = []
    for s in stations:
        snap = registry.get(s.id)
        out.append(
            {
                "id": s.id,
                "station_code": s.station_code,
                "name": s.name,
                "status": s.status,
                "live_state": snap.state if snap else None,
                "last_seen": snap.last_seen if snap else None,
            }
        )
    return {"items": out}


@router.get("/deposits")
def list_deposits(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    from sqlalchemy import func

    from ..models import DepositSession, Station, User, WasteEvent

    total = db.execute(
        select(func.count()).select_from(DepositSession)
    ).scalar_one()
    rows = db.execute(
        select(
            DepositSession, User.email, Station.station_code, WasteEvent.points_awarded
        )
        .join(User, DepositSession.user_id == User.id)
        .join(Station, DepositSession.station_id == Station.id)
        .outerjoin(WasteEvent, WasteEvent.operation_id == DepositSession.operation_id)
        .order_by(DepositSession.created_at.desc(), DepositSession.operation_id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [
            {
                "operation_id": ds.operation_id,
                "student": email,
                "station": code,
                "ai_class": ds.expected_class,
                "confidence": round(ds.confidence, 3) if ds.confidence else None,
                "routing": (
                    f"compartment {ds.actual_position}"
                    if ds.actual_position
                    else (f"expected {ds.expected_position}" if ds.expected_position else None)
                ),
                "expected_weight_g": None,
                "measured_weight_g": ds.weight_grams,
                "status": ds.status,
                "reject_reason": ds.reject_reason,
                # Authoritative award lives on waste_events (NULL when the
                # deposit never completed) — never a client claim.
                "points": points or 0,
                "created_at": ds.created_at.isoformat() if ds.created_at else None,
            }
            for ds, email, code, points in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


# -- rewards marketplace -------------------------------------------------------
# Catalog management + the cash-fulfillment queue. Fulfillment is an explicit,
# audited action — nothing here moves real money automatically.


class RewardUpsert(BaseModel):
    category: str  # cash | food | printing | discount
    name: str
    description: str = ""
    provider: str = ""
    points_cost: int
    value_label: str
    value_amount: float | None = None
    currency: str = "EGP"
    icon: str = "card_giftcard"
    is_active: bool = True
    stock: int | None = None  # None = unlimited
    requires_destination: bool = False


REWARD_CATEGORIES = {"cash", "food", "printing", "discount"}


def _validate_reward_payload(payload: RewardUpsert) -> None:
    if payload.category not in REWARD_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail="Category must be one of: cash, food, printing, discount.",
        )
    if not (1 <= len(payload.name.strip()) <= 128):
        raise HTTPException(status_code=422, detail="Reward name must be 1-128 characters.")
    if payload.points_cost < 1:
        raise HTTPException(status_code=422, detail="Points cost must be at least 1.")
    if not (1 <= len(payload.value_label.strip()) <= 64):
        raise HTTPException(status_code=422, detail="Value label must be 1-64 characters.")
    if payload.stock is not None and payload.stock < 0:
        raise HTTPException(status_code=422, detail="Stock cannot be negative.")
    if payload.category == "cash" and not payload.requires_destination:
        raise HTTPException(
            status_code=422,
            detail="Cash rewards require a payout destination from the student.",
        )


@router.get("/rewards")
def list_rewards_admin(db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import func

    from ..models import RewardRedemption

    counts = dict(
        db.execute(
            select(RewardRedemption.reward_id, func.count(RewardRedemption.id)).group_by(
                RewardRedemption.reward_id
            )
        ).all()
    )
    rewards = db.execute(select(Reward).order_by(Reward.created_at.desc())).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "category": r.category,
                "name": r.name,
                "description": r.description,
                "provider": r.provider,
                "points_cost": r.points_cost,
                "value_label": r.value_label,
                "value_amount": r.value_amount,
                "currency": r.currency,
                "icon": r.icon,
                "is_active": r.is_active,
                "stock": r.stock,
                "requires_destination": r.requires_destination,
                "redemption_count": int(counts.get(r.id, 0)),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rewards
        ]
    }


@router.post("/rewards")
def create_reward(payload: RewardUpsert, db: Session = Depends(get_db)) -> dict:
    _validate_reward_payload(payload)
    reward = Reward(
        id=f"rw-{uuid.uuid4().hex[:10]}",
        category=payload.category,
        name=payload.name.strip(),
        description=payload.description.strip()[:512],
        provider=payload.provider.strip()[:128],
        points_cost=payload.points_cost,
        value_label=payload.value_label.strip(),
        value_amount=payload.value_amount,
        currency=payload.currency.strip()[:8] or "EGP",
        icon=payload.icon.strip()[:32] or "card_giftcard",
        is_active=payload.is_active,
        stock=payload.stock,
        requires_destination=payload.requires_destination,
    )
    db.add(reward)
    db.commit()
    return {"id": reward.id, "name": reward.name}


@router.patch("/rewards/{reward_id}")
def patch_reward(
    reward_id: str, payload: RewardUpsert, db: Session = Depends(get_db)
) -> dict:
    """Full replace of editable fields (admin panel edits a form)."""
    reward = db.get(Reward, reward_id)
    if reward is None:
        raise HTTPException(status_code=404, detail="This reward could not be found.")
    _validate_reward_payload(payload)
    reward.category = payload.category
    reward.name = payload.name.strip()
    reward.description = payload.description.strip()[:512]
    reward.provider = payload.provider.strip()[:128]
    reward.points_cost = payload.points_cost
    reward.value_label = payload.value_label.strip()
    reward.value_amount = payload.value_amount
    reward.currency = payload.currency.strip()[:8] or "EGP"
    reward.icon = payload.icon.strip()[:32] or "card_giftcard"
    reward.is_active = payload.is_active
    reward.stock = payload.stock
    reward.requires_destination = payload.requires_destination
    db.commit()
    return {"id": reward.id, "is_active": reward.is_active}


@router.delete("/rewards/{reward_id}")
def delete_reward(reward_id: str, db: Session = Depends(get_db)) -> dict:
    from ..models import RewardRedemption

    reward = db.get(Reward, reward_id)
    if reward is None:
        raise HTTPException(status_code=404, detail="This reward could not be found.")
    used = db.execute(
        select(sa_func.count()).select_from(RewardRedemption).where(
            RewardRedemption.reward_id == reward_id
        )
    ).scalar_one()
    if used:
        raise HTTPException(
            status_code=409,
            detail="This reward already has redemptions. Deactivate it instead to keep history intact.",
        )
    db.delete(reward)
    db.commit()
    return {"deleted": reward_id}


class RedemptionAction(BaseModel):
    admin_note: str | None = None


def _load_redemption(db: Session, redemption_id: str) -> RewardRedemption:
    rd = db.get(RewardRedemption, redemption_id)
    if rd is None:
        raise HTTPException(status_code=404, detail="Redemption not found.")
    return rd


@router.get("/rewards/redemptions")
def list_redemptions(
    status: str = Query("", max_length=16),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    from ..models import RewardRedemption

    base = select(RewardRedemption).order_by(RewardRedemption.created_at.desc())
    if status:
        base = base.where(RewardRedemption.status == status)
    total = db.execute(
        select(sa_func.count()).select_from(base.subquery())
    ).scalar_one()
    rows = db.execute(base.limit(limit).offset(offset)).scalars().all()

    user_ids = {r.user_id for r in rows}
    users = {
        u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    } if user_ids else {}
    rewards = {r.id: r for r in db.execute(select(Reward)).scalars().all()}

    items = []
    for rd in rows:
        u = users.get(rd.user_id)
        rw = rewards.get(rd.reward_id)
        dest = rd.destination or ""
        items.append(
            {
                "id": rd.id,
                "status": rd.status,
                "points_spent": rd.points_spent,
                "created_at": rd.created_at.isoformat() if rd.created_at else None,
                "fulfilled_at": rd.fulfilled_at.isoformat() if rd.fulfilled_at else None,
                "redemption_code": rd.redemption_code,
                "admin_note": rd.admin_note,
                "destination_masked": (
                    dest[:4] + "*" * max(len(dest) - 7, 3) + dest[-3:]
                    if len(dest) > 7
                    else ("***" if dest else None)
                ),
                "student": {
                    "id": rd.user_id,
                    "name": u.name if u else "(deleted)",
                    "email": u.email if u else "(deleted)",
                    "student_code": u.student_code if u else "",
                },
                "reward": {
                    "id": rd.reward_id,
                    "name": rw.name if rw else rd.reward_id,
                    "category": rw.category if rw else "",
                    "provider": rw.provider if rw else "",
                    "value_label": rw.value_label if rw else "",
                },
            }
        )
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


@router.post("/rewards/redemptions/{redemption_id}/approve")
def approve_redemption(
    redemption_id: str, payload: RedemptionAction, db: Session = Depends(get_db)
) -> dict:
    rd = _load_redemption(db, redemption_id)
    if rd.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending redemptions can be approved.")
    rd.status = "approved"
    rd.admin_note = (payload.admin_note or "").strip()[:512] or None
    db.commit()
    return {"id": rd.id, "status": rd.status}


@router.post("/rewards/redemptions/{redemption_id}/fulfill")
def fulfill_redemption(
    redemption_id: str, payload: RedemptionAction, db: Session = Depends(get_db)
) -> dict:
    from datetime import datetime, timezone as tz

    rd = _load_redemption(db, redemption_id)
    reward = db.get(Reward, rd.reward_id)
    if reward is None or reward.category != "cash":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only cash payouts are fulfilled by admins. "
                "Code rewards are consumed via mark-used."
            ),
        )
    if rd.status not in {"pending", "approved"}:
        raise HTTPException(
            status_code=409,
            detail="Only pending or approved redemptions can be fulfilled.",
        )
    rd.status = "fulfilled"
    rd.fulfilled_at = datetime.now(tz.utc)
    rd.admin_note = (payload.admin_note or "").strip()[:512] or None
    db.commit()
    return {"id": rd.id, "status": rd.status}


@router.post("/rewards/redemptions/{redemption_id}/reject")
def reject_redemption(
    redemption_id: str, payload: RedemptionAction, db: Session = Depends(get_db)
) -> dict:
    from ..services.reward_service import RewardError, admin_reject

    rd = _load_redemption(db, redemption_id)
    note = (payload.admin_note or "").strip()
    try:
        admin_reject(db, rd, note)
    except RewardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return {"id": rd.id, "status": rd.status}


@router.post("/rewards/redemptions/{redemption_id}/mark-used")
def mark_used(redemption_id: str, db: Session = Depends(get_db)) -> dict:
    """Merchant-side confirmation that an available code was consumed.

    Atomic transition: the conditional UPDATE wins only if the row is STILL
    available at write time — a student cancel (or another mark-used) that
    committed first makes this a no-op 409, never a second terminal move."""
    rd = _load_redemption(db, redemption_id)
    won = db.execute(
        update(RewardRedemption)
        .where(
            RewardRedemption.id == rd.id,
            RewardRedemption.status == "available",
        )
        .values(status="used")
        .execution_options(synchronize_session=False)
    )
    if won.rowcount == 0:
        raise HTTPException(status_code=409, detail="Only available codes can be marked used.")
    rd.status = "used"
    db.commit()
    return {"id": rd.id, "status": rd.status}
