#!/usr/bin/env python
"""Bootstrap the FIRST SCWT administrator account.

Administrative tool only — run it on the server (or against a reachable
DATABASE_URL). It is NOT part of any user-facing flow.

Usage:
    python scripts/create_admin.py --email admin@university.edu

    The script prompts for the password interactively (hidden input, asked
    twice). It never accepts a password argument or prints the password.

    Refuses to overwrite an existing account unless --force is given, and
    refuses weak passwords (< 12 chars).

Environment:
    DATABASE_URL  backend database URL (same as the backend uses).
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

MIN_PASSWORD_LEN = 12


def _build_app_imports():
    from app.database import SessionLocal, create_tables
    from app.models import User
    from app.security.password import hash_password

    return SessionLocal, create_tables, User, hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="admin login email")
    parser.add_argument(
        "--force",
        action="store_true",
        help="if the email already exists, REPLACE its password and promote it to admin",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        print("ERROR: --email must be a valid email address", file=sys.stderr)
        return 2

    password = getpass.getpass("Admin password (min %d chars): " % MIN_PASSWORD_LEN)
    if len(password) < MIN_PASSWORD_LEN:
        print(f"ERROR: password must be at least {MIN_PASSWORD_LEN} characters", file=sys.stderr)
        return 2
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("ERROR: passwords do not match", file=sys.stderr)
        return 2

    try:
        SessionLocal, create_tables, User, hash_password = _build_app_imports()
    except ImportError as exc:
        print(f"ERROR: backend imports failed ({exc}). Run from the repo root "
              "with the project venv active.", file=sys.stderr)
        return 2

    # Ensure schema exists so FKs (faculty) resolve on a fresh database.
    # Faculties themselves are seeded by the backend startup seed; on a live
    # database they are already present.
    create_tables()

    with SessionLocal() as db:
        existing = db.query(User).filter(User.email == email).first()
        if existing is not None and not args.force:
            print(
                f"ERROR: an account already exists for {email}. "
                "Re-run with --force to replace its credentials.",
                file=sys.stderr,
            )
            return 1

        if existing is None:
            # An admin is not a faculty member per se — attach to the first
            # canonical faculty for FK integrity.
            from app.models import Faculty

            faculty = db.query(Faculty).order_by(Faculty.id).first()
            if faculty is None:
                print("ERROR: no faculties seeded; cannot attach admin user", file=sys.stderr)
                return 2
            user = User(
                email=email,
                student_code=f"ADMIN-{email.split('@')[0][:8].upper()}",
                name=email.split("@")[0],
                password_hash=hash_password(password),
                faculty_id=faculty.id,
                points=0,
                role="admin",
                email_verified=True,
            )
            db.add(user)
            action = "created"
        else:
            existing.password_hash = hash_password(password)
            existing.role = "admin"
            existing.email_verified = True
            existing.token_version = (existing.token_version or 0) + 1
            user = existing
            action = "replaced credentials for"

        db.commit()
        print(f"OK: {action} admin account {email} (id={user.id})")
        print("This account authenticates through the admin interface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
