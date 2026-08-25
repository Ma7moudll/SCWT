from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AiPrediction, RoutingPolicy, User
from .ai_client import AiExternalPrediction, AiServiceClient

VALID_CLASSES = {"plastic", "metal", "paper", "other"}


def confidence_level_for(confidence: float) -> str:
    if confidence >= settings.ai_high_confidence:
        return "high"
    if confidence >= settings.ai_medium_confidence:
        return "medium"
    return "low"


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def serializable_prediction(pred: AiPrediction, position: int, potential_points: int, recyclable: bool) -> dict:
    return {
        "prediction_id": pred.id,
        "operation_id": pred.operation_id,
        "predicted_class": pred.predicted_class,
        "confidence": pred.confidence,
        "confidence_level": pred.confidence_level,
        "recyclable": recyclable,
        "destination_position": position,
        "potential_points": potential_points,
        "expires_at": _naive_utc(pred.expires_at).isoformat(),
        "source": pred.source,
    }


class PredictService:
    def __init__(self, ai: AiServiceClient | None = None) -> None:
        self.ai = ai or AiServiceClient()

    def predict(
        self,
        db: Session,
        user: User,
        image_bytes: bytes,
        image_url: str | None = None,
    ) -> dict:
        """FULL pipeline: real AI service call -> confidence policy -> DB
        routing policy -> persisted ai_predictions row -> wire Prediction."""
        ext = self.ai.predict(image_bytes)
        return self.from_external(db, user, ext, image_bytes=image_bytes, image_url=image_url)

    def from_external(
        self,
        db: Session,
        user: User,
        ext: AiExternalPrediction,
        image_bytes: bytes | None = None,
        image_url: str | None = None,
    ) -> dict:
        cls = ext.predicted_class.strip().lower()
        if cls not in VALID_CLASSES:
            raise ValueError(f"Unknown predicted class: {cls!r}")

        policy = db.execute(
            select(RoutingPolicy).where(RoutingPolicy.waste_class == cls)
        ).scalar_one()

        now = datetime.now(timezone.utc)
        pred = AiPrediction(
            id=f"pred-{uuid.uuid4().hex[:12]}",
            operation_id=f"OP-PRED-{uuid.uuid4().hex[:10].upper()}",
            image_url=image_url,
            predicted_class=cls,
            confidence=ext.confidence,
            confidence_level=confidence_level_for(ext.confidence),
            source="ai" if ext.model != "development" else "demo",
            routing_policy_id=policy.id,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.deposit_session_ttl_seconds),
        )
        db.add(pred)
        db.commit()
        db.refresh(pred)
        return serializable_prediction(
            pred,
            position=policy.position,
            potential_points=policy.potential_points,
            recyclable=cls != "other",
        )