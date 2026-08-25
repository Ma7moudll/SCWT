"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "faculties",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "stations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("station_code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'offline'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "routing_policies",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("waste_class", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("potential_points", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("waste_class", name="uq_routing_class"),
    )
    op.create_table(
        "operation_counters",
        sa.Column("day", sa.String(length=8), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("student_code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("faculty_id", sa.String(length=64), sa.ForeignKey("faculties.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "ai_predictions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("operation_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("predicted_class", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_level", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default=sa.text("'ai'")),
        sa.Column("routing_policy_id", sa.String(length=64), sa.ForeignKey("routing_policies.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "deposit_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("station_id", sa.String(length=64), sa.ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ai_prediction_id", sa.String(length=64), sa.ForeignKey("ai_predictions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("routing_policy_id", sa.String(length=64), sa.ForeignKey("routing_policies.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("potential_points", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("expected_class", sa.String(length=32), nullable=False),
        sa.Column("expected_position", sa.Integer(), nullable=False),
        sa.Column("actual_position", sa.Integer(), nullable=True),
        sa.Column("weight_grams", sa.Float(), nullable=True),
        sa.Column("weight_stable", sa.Boolean(), nullable=True),
        sa.Column("mechanical_confirmed", sa.Boolean(), nullable=True),
        sa.Column("reject_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("operation_id", name="uq_deposit_operation_id"),
    )
    op.create_table(
        "waste_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("station_id", sa.String(length=64), sa.ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deposit_session_id", sa.String(length=64), sa.ForeignKey("deposit_sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ai_prediction_id", sa.String(length=64), sa.ForeignKey("ai_predictions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("predicted_class", sa.String(length=32), nullable=False),
        sa.Column("actual_position", sa.Integer(), nullable=False),
        sa.Column("weight_grams", sa.Float(), nullable=False),
        sa.Column("mechanical_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("points_awarded", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'confirmed'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("operation_id", name="uq_waste_operation_id"),
    )
    op.create_table(
        "challenges",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("theme_emoji", sa.String(length=8), nullable=False, server_default=sa.text("'♻️'")),
        sa.Column("waste_class", sa.String(length=32), nullable=False),
        sa.Column("target_kg", sa.Float(), nullable=False),
        sa.Column("reward_points", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "leaderboard_entries",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("detail", sa.String(length=128), nullable=False, server_default=sa.text("''")),
        sa.Column("points", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("faculty_id", sa.String(length=64), sa.ForeignKey("faculties.id", ondelete="CASCADE"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("scope", "entity_id", name="uq_leaderboard_scope_entity"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_deposit_sessions_operation_id", "deposit_sessions", ["operation_id"])
    op.create_index("ix_waste_events_operation_id", "waste_events", ["operation_id"])
    op.create_index("ix_waste_events_created_at", "waste_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("leaderboard_entries")
    op.drop_table("challenges")
    op.drop_table("waste_events")
    op.drop_table("deposit_sessions")
    op.drop_table("ai_predictions")
    op.drop_table("users")
    op.drop_table("operation_counters")
    op.drop_table("routing_policies")
    op.drop_table("stations")
    op.drop_table("faculties")