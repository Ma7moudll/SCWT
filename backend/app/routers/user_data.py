from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Faculty, User
from ..repositories import WasteRepository
from ..schemas import UserOut
from ..security import get_current_user
from ..services import ChallengeService, ImpactService, LeaderboardService

router = APIRouter(tags=["user-data"])

# Pagination caps: safe defaults, hard ceilings so a huge limit cannot be
# used to pull the whole table in one request.
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, _MAX_LIMIT)), max(0, offset)


@router.get("/users/me")
def me(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    from .auth import payload_fields

    return {"user": payload_fields(db, user)}


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    faculty_id: str | None = Field(None, max_length=64)


# Allowed avatar image types (magic-byte verified, not just content-type).
_AVATAR_MAGIC = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/webp": b"RIFF",
}


def _avatars_dir() -> Path:
    from ..config import settings

    path = Path(settings.avatars_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _avatar_path(user_id: str) -> Path:
    return _avatars_dir() / f"{user_id}.jpg"


@router.put("/users/me/avatar", response_model=UserOut)
async def upload_avatar(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    """Upload a profile photo (multipart form field `file`).

    Accepts JPEG/PNG/WebP up to `avatar_max_bytes`; the bytes are
    magic-byte-verified and stored on the server filesystem. Every upload
    bumps `avatar_version` so clients can cache-bust."""
    from .auth import payload_fields

    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=422,
            detail="Please attach the photo as a multipart file upload.",
        )

    form = await request.form()
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise HTTPException(status_code=422, detail="Please choose a photo to upload.")

    data = await upload.read()
    from ..config import settings

    if not data:
        raise HTTPException(status_code=422, detail="The selected photo is empty. Please try another one.")
    if len(data) > settings.avatar_max_bytes:
        raise HTTPException(
            status_code=413,
            detail="That photo is too large. Please choose one under 2 MB.",
        )
    if not any(data.startswith(magic) for magic in _AVATAR_MAGIC.values()):
        raise HTTPException(
            status_code=422,
            detail="That file is not a supported image. Please use JPG, PNG or WebP.",
        )

    _avatar_path(user.id).write_bytes(data)
    user.avatar_version = int(user.avatar_version or 0) + 1
    db.commit()
    db.refresh(user)
    return UserOut(user=payload_fields(db, user))


@router.delete("/users/me/avatar", response_model=UserOut)
def remove_avatar(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserOut:
    """Remove the profile photo (bumps the version so caches invalidate)."""
    from .auth import payload_fields

    path = _avatar_path(user.id)
    if path.exists():
        path.unlink()
    user.avatar_version = 0
    db.commit()
    db.refresh(user)
    return UserOut(user=payload_fields(db, user))


@router.get("/users/avatar/{user_id}")
def get_avatar(user_id: str) -> FileResponse:
    """Serves a student's profile photo. Photos are non-sensitive by design;
    the version query parameter allows clients to cache aggressively."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        raise HTTPException(status_code=404, detail="This photo could not be found.")
    path = _avatar_path(user_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="This photo could not be found.")
    return FileResponse(path, media_type="image/jpeg")


@router.patch("/users/me/profile", response_model=UserOut)
def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    """Edit display name and/or faculty. Email, student code and role are
    identity fields and are deliberately NOT editable here."""
    from .auth import payload_fields

    if payload.name is None and payload.faculty_id is None:
        raise HTTPException(status_code=422, detail="There are no changes to save.")

    if payload.name is not None and not payload.name.strip():
        raise HTTPException(status_code=422, detail="Your name cannot be empty.")

    if payload.faculty_id is not None:
        exists = db.execute(
            select(sa_func.count()).select_from(Faculty).where(
                Faculty.id == payload.faculty_id
            )
        ).scalar_one()
        if not exists:
            raise HTTPException(status_code=422, detail="Please select a valid faculty.")

    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.faculty_id is not None:
        user.faculty_id = payload.faculty_id
    db.commit()
    db.refresh(user)
    return UserOut(user=payload_fields(db, user))


@router.get("/waste/history")
def history(
    limit: int = Query(_DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from .auth import faculty_name

    size, skip = _page(limit, offset)
    repo = WasteRepository()
    events, total = repo.list_by_user_paged(db, user.id, size, skip)
    return {
        "items": [
            {
                "id": e.id,
                "operation_id": e.operation_id,
                "station_id": e.station_id,
                "predicted_class": e.predicted_class,
                "weight_g": round(e.weight_grams, 2),
                "points_awarded": e.points_awarded,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "total": total,
        "limit": size,
        "offset": skip,
    }


@router.get("/waste/history/{event_id}")
def history_event(
    event_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    repo = WasteRepository()
    event = repo.get(db, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status_code=404, detail="This event could not be found.")
    return {
        "item": {
            "id": event.id,
            "operation_id": event.operation_id,
            "station_id": event.station_id,
            "predicted_class": event.predicted_class,
            "weight_g": round(event.weight_grams, 2),
            "points_awarded": event.points_awarded,
            "created_at": event.created_at.isoformat(),
        }
    }


@router.get("/impact")
def impact(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return ImpactService().for_user(db, user)


@router.get("/leaderboard")
def leaderboard(
    scope: str = "students",
    limit: int = Query(_DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    size, skip = _page(limit, offset)
    entries, total = LeaderboardService().get_entries_paged(db, scope, size, skip)
    return {"entries": entries, "total": total, "limit": size, "offset": skip}


@router.get("/leaderboard/students")
def leaderboard_students(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return {"entries": LeaderboardService().get_entries(db, "students")}


@router.get("/leaderboard/faculties")
def leaderboard_faculties(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return {"entries": LeaderboardService().get_entries(db, "faculties")}


@router.get("/challenges")
def challenges(
    limit: int = Query(_DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    size, skip = _page(limit, offset)
    items, total = ChallengeService().list_for_user_paged(db, user, size, skip)
    return {"items": items, "total": total, "limit": size, "offset": skip}