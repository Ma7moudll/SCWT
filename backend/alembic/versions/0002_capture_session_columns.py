"""station-camera capture columns

Revision ID: 0002_capture_session_columns
Revises: 0001_initial
Create Date: 2026-08-19

Brings `deposit_sessions` up to the FINAL station-camera architecture:
capture-first sessions exist with NO prediction yet, so `ai_prediction_id`,
`expected_class` and `expected_position` become nullable, and the session
carries the station-camera prediction's `confidence` / `confidence_level`.

Without this migration a capture-first session insert fails with
"column deposit_sessions.confidence does not exist" and the AI service can
never attach its classification onto the session.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_capture_session_columns"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("deposit_sessions", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "deposit_sessions",
        sa.Column("confidence_level", sa.String(length=16), nullable=True),
    )
    # Capture-first sessions start with no prediction attached; the station
    # camera classification arrives later via /deposit/capture.
    op.alter_column("deposit_sessions", "ai_prediction_id", nullable=True)
    op.alter_column("deposit_sessions", "expected_class", nullable=True)
    op.alter_column("deposit_sessions", "expected_position", nullable=True)


def downgrade() -> None:
    op.alter_column("deposit_sessions", "expected_position", nullable=False)
    op.alter_column("deposit_sessions", "expected_class", nullable=False)
    op.alter_column("deposit_sessions", "ai_prediction_id", nullable=False)
    op.drop_column("deposit_sessions", "confidence_level")
    op.drop_column("deposit_sessions", "confidence")
