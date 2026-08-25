from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class RoutingPolicy(Base):
    """Database-driven routing: predicted class -> compartment position + points.

    Seeded rows: plastic->1(5), metal->2(10), paper->3(5), other->4(0).
    The mapping is NEVER hardcoded in the Flutter client.
    """

    __tablename__ = "routing_policies"
    __table_args__ = (UniqueConstraint("waste_class", name="uq_routing_class"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    waste_class: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    potential_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoutingPolicyFK(Base):
    """Shared columns helper is not a table; kept here for documentation.

    `ai_predictions` and `deposit_sessions` reference routing_policies.id via
    the ForeignKey declared on their own models.
    """

    __abstract__ = True
    routing_policy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("routing_policies.id", ondelete="RESTRICT"), nullable=True
    )