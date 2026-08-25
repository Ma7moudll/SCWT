from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Station(Base):
    """One physical EcoLoop unit (single body, four internal compartments).

    Compartments are positions 1..4 defined by routing_policy, not separate
    station entities.
    """

    __tablename__ = "stations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    station_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="offline")
    # Ecolamp stations use the CARRIAGE sorting mechanism. Kept as explicit
    # station metadata so ops tooling can display it.
    mechanism: Mapped[str] = mapped_column(String(16), nullable=False, default="carriage")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )