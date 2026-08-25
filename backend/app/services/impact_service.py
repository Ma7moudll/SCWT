from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, WasteEvent

# kg of CO2 saved per kg recycled (documented placeholder constant).
CO2_PER_KG = 0.5


class ImpactService:
    def for_user(self, db: Session, user: User) -> dict:
        events = list(
            db.execute(
                select(WasteEvent).where(
                    WasteEvent.user_id == user.id,
                    WasteEvent.status == "confirmed",
                    WasteEvent.points_awarded > 0,
                )
            ).scalars()
        )
        recycled_kg = 0.0
        items = 0
        kg_by_class: dict[str, float] = defaultdict(float)
        count_by_class: dict[str, int] = defaultdict(int)
        for e in events:
            recycled_kg += e.weight_grams / 1000.0
            items += 1
            if e.predicted_class in ("plastic", "metal", "paper"):
                kg_by_class[e.predicted_class] += e.weight_grams / 1000.0
                count_by_class[e.predicted_class] += 1

        classes = ("plastic", "metal", "paper", "other")
        breakdown = [
            {
                "waste_class": cls,
                "kg": round(kg_by_class[cls], 3),
                "count": count_by_class[cls],
            }
            for cls in classes
        ]
        return {
            "total_points": user.points,
            "recycled_kg": round(recycled_kg, 3),
            "items_recycled": items,
            "co2_saved_kg": round(recycled_kg * CO2_PER_KG, 3),
            "breakdown": breakdown,
        }