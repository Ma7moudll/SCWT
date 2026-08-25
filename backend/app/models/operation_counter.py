from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class OperationCounter(Base):
    """Per-day sequential counter used to mint readable `OP-YYYYMMDD-NNNNNN`
    operation ids. Read + increment happens inside the deposit transaction
    with a row lock so ids are never duplicated."""

    __tablename__ = "operation_counters"

    day: Mapped[str] = mapped_column(String(8), primary_key=True)  # YYYYMMDD
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)