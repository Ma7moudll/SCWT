from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, UploadFile

from ..models import User
from ..security import get_current_user

# Debug-only surface for proving byte identity end-to-end. This router is only
# mounted when `DEBUG_IMAGE_HASH=true` (see app/main.py) so it never exists for
# normal users. It performs no inference and persists nothing — it only echoes
# a fingerprint of the exact bytes the HTTP layer received, which the hardware
# validation harness compares against the SHA-256 the station camera computed
# on-device (byte-identity proof that no re-processing happened in transit).
router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/image-sha256")
def image_sha256(
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    data = image.file.read()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }