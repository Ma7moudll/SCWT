"""users.avatar_version — profile photo support.

The avatar image itself lives on the server filesystem
(`avatars_dir`/<user_id>.jpg); this integer is bumped on every upload so
clients can cache-bust (`GET /users/avatar/{id}?v=n`) and detect removal.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_user_avatar_version"
down_revision = "0006_user_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("avatar_version", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar_version")
