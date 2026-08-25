"""Hardening schema: user roles/verification, auth tokens, per-user challenges.

- users.role ("student"|"admin") gates management endpoints.
- users.email_verified supports the email verification flow.
- auth_tokens stores HASHED one-time tokens (password reset, verification).
- user_challenges persists per-user challenge completion; the unique
  (user_id, challenge_id) constraint makes duplicate rewards impossible.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_hardening_auth_challenges"
down_revision: Union[str, None] = "0002_capture_session_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="student"),
    )
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_purpose", "auth_tokens", ["purpose"])
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"])
    op.create_table(
        "user_challenges",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "challenge_id", sa.String(length=64), sa.ForeignKey("challenges.id"), nullable=False
        ),
        sa.Column("reward_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "challenge_id", name="uq_user_challenge"),
    )
    op.create_index("ix_user_challenges_user_id", "user_challenges", ["user_id"])
    op.create_index("ix_user_challenges_challenge_id", "user_challenges", ["challenge_id"])


def downgrade() -> None:
    op.drop_index("ix_user_challenges_challenge_id", table_name="user_challenges")
    op.drop_index("ix_user_challenges_user_id", table_name="user_challenges")
    op.drop_table("user_challenges")
    op.drop_index("ix_auth_tokens_token_hash", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_purpose", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "role")
