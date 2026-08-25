from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user
from ..services import PredictService
from ..services.ai_client import AiGateRejection, AiWireError

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/predict")
def predict(
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    image_bytes = image.file.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="The uploaded image is empty. Please try again.")
    try:
        return PredictService().predict(db, user, image_bytes)
    except AiGateRejection as exc:
        # Frame rejected by the AI camera gate BEFORE classification. No
        # prediction is persisted and no deposit session can be created.
        # `error` at the top level feeds the mobile retake flow verbatim.
        return JSONResponse(
            status_code=422,
            content={"code": exc.code, "error": exc.detail},
        )
    except AiWireError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc