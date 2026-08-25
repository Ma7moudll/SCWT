"""Faculty canonicalisation: only the three real university faculties.

Replaces the prototype faculty set (engineering / science / commerce /
medicine) with the stable identifiers used across backend + mobile:

    ENGINEERING        -> Engineering
    PHYSICAL_THERAPY   -> Physical Therapy
    ART_DESIGN         -> Art & Design

Legacy rows are retired: users are remapped by name match where possible
and to ENGINEERING otherwise (the legacy extra faculties were demo-only;
no real cohort ever existed on them). Leaderboard rows pointing at retired
faculties are deleted — the startup repair rebuilds them.
"""
from alembic import op

revision = "0005_faculty_canonical"
down_revision = "0004_challenge_bools"
branch_labels = None
depends_on = None

_BIND = op.get_bind()
_IS_PG = _BIND.dialect.name == "postgresql"

CANONICAL = [
    ("ENGINEERING", "Engineering"),
    ("PHYSICAL_THERAPY", "Physical Therapy"),
    ("ART_DESIGN", "Art & Design"),
]

# old id -> new id (name-normalised matches first, demo faculties retire).
REMAP = {
    "engineering": "ENGINEERING",
    "science": "ENGINEERING",
    "commerce": "ENGINEERING",
    "medicine": "ENGINEERING",
}


def upgrade() -> None:
    if not _IS_PG:
        return  # SQLite test DBs are recreated from models/seed each run.
    for fid, name in CANONICAL:
        _BIND.execute(
            sa_text_insert_faculties(), {"fid": fid, "name": name}
        )
    for old, new in REMAP.items():
        _BIND.execute(
            sa_text_remap_users(), {"old": old, "new": new}
        )
    _BIND.execute(sa_text_delete_retired_leaderboard())
    for old in REMAP:
        _BIND.execute(sa_text_delete_faculty(), {"old": old})


def downgrade() -> None:
    if not _IS_PG:
        return
    # Downgrade re-creates the legacy engineering row and moves users back;
    # retired demo faculties are NOT resurrected (they held no real users).
    _BIND.execute(
        sa_text_insert_faculties(), {"fid": "engineering", "name": "Faculty of Engineering"}
    )
    _BIND.execute(
        sa_text_remap_users(), {"old": "ENGINEERING", "new": "engineering"}
    )
    for fid, _ in CANONICAL:
        _BIND.execute(sa_text_delete_faculty(), {"old": fid})


def sa_text_insert_faculties():
    from sqlalchemy import text

    return text(
        "INSERT INTO faculties (id, name) VALUES (:fid, :name) "
        "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
    )


def sa_text_remap_users():
    from sqlalchemy import text

    return text(
        "UPDATE users SET faculty_id = :new WHERE faculty_id = :old"
    )


def sa_text_delete_retired_leaderboard():
    from sqlalchemy import text

    return text(
        "DELETE FROM leaderboard_entries WHERE scope = 'faculties' "
        "AND entity_id IN ('science', 'commerce', 'medicine')"
    )


def sa_text_delete_faculty():
    from sqlalchemy import text

    return text("DELETE FROM faculties WHERE id = :old")
