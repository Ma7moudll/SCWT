"""stations.mechanism — which mechanical sorting implementation a unit runs.

`carriage` (V1) or `rotary` (V2). Domain metadata only: commands always
express compartment intent (`destination_position`) and never mechanics, so
both mechanisms implement the same station-level software contract.

Revision ID: 0009_station_mechanism
Revises: 0008_rewards
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_station_mechanism"
down_revision = "0008_rewards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stations",
        sa.Column("mechanism", sa.String(16), nullable=False, server_default="carriage"),
    )


def downgrade() -> None:
    op.drop_column("stations", "mechanism")
