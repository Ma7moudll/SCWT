"""Rewards marketplace — rewards + reward_redemptions.

rewards            : the catalog admin manages (Vodafone Cash, InstaPay,
                     MIX Coffee discounts, copy-center credit).
reward_redemptions : one row per user redemption. Points are deducted in the
                     SAME transaction that inserts the redemption (see
                     services/reward_service.py), so a redemption can never
                     exist without its matching deduction and vice versa.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_rewards"
down_revision = "0007_user_avatar_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rewards",
        sa.Column("id", sa.String(64), primary_key=True),
        # cash | food | printing | discount
        sa.Column("category", sa.String(16), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=False, server_default=""),
        sa.Column("provider", sa.String(128), nullable=False, server_default=""),
        sa.Column("points_cost", sa.Integer(), nullable=False),
        # Human-readable value, e.g. "10 EGP" or "20% OFF".
        sa.Column("value_label", sa.String(64), nullable=False),
        # Numeric value for sorting/reporting (10, 0.20, 30 ...). Nullable:
        # percentage rewards keep the number in value_label semantics.
        sa.Column("value_amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="EGP"),
        sa.Column("icon", sa.String(32), nullable=False, server_default="card_giftcard"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        # NULL = unlimited stock; otherwise remaining count.
        sa.Column("stock", sa.Integer(), nullable=True),
        # cash payouts need a destination (phone / InstaPay handle). The
        # mobile app asks for it at redeem time; we never store credentials.
        sa.Column("requires_destination", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "reward_redemptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "reward_id", sa.String(64),
            sa.ForeignKey("rewards.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column("points_spent", sa.Integer(), nullable=False),
        # pending | approved | fulfilled | rejected | cancelled  (cash flow)
        # available | used                                       (code flow)
        sa.Column("status", sa.String(16), nullable=False, index=True),
        # Unique, non-guessable merchant code (code-type rewards only).
        sa.Column("redemption_code", sa.String(16), nullable=True, unique=True),
        # Destination snapshot for cash rewards (phone / handle). Masked in
        # student-facing responses; never logged.
        sa.Column("destination", sa.String(128), nullable=True),
        sa.Column("admin_note", sa.String(512), nullable=True),
        # Client-supplied idempotency key: one redemption per key, enforced
        # by a unique constraint — retries can never double-spend.
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_redemption_idem"),
    )


def downgrade() -> None:
    op.drop_table("reward_redemptions")
    op.drop_table("rewards")
