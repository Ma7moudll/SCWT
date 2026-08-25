"""users.token_version — credential-change token invalidation.

JWTs carry a `ver` claim; security.deps refuses tokens whose version is older
than the user's current one. Password change/reset bumps the column so every
outstanding session dies immediately (a stolen token cannot survive a
credential change).
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_user_token_version"
down_revision = "0005_faculty_canonical"
branch_labels = None
depends_on = None

_BIND = op.get_bind()
_IS_PG = _BIND.dialect.name == "postgresql"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
