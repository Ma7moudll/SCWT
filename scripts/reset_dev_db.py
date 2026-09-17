#!/usr/bin/env python
"""Reset the DEVELOPMENT database to a clean, fully real state.

Drops and recreates the schema, then runs the config-only seed (faculties,
the station, the routing policy, the operation counter) — with NO demo user,
NO fabricated leaderboard, NO seeded activity. The database is then empty of
any runtime data; all points arrive only through the real AI -> MQTT ->
simulator -> backend chain.

    scripts/reset_dev_db.py            # default dev stack (scwt)
    scripts/reset_dev_db.py --db e2e   # the e2e harness database

This is intentionally destructive — it truncates the target database entirely.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

DB_ALIASES = {
    "dev": "postgresql+psycopg2://scwt:scwt@localhost:5432/scwt_db",
    "e2e": "postgresql+psycopg2://scwt:scwt@localhost:5432/scwt_db_e2e",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        choices=list(DB_ALIASES) + ["url"],
        default="dev",
        help="database alias to reset (default: dev)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="explicit SQLAlchemy URL when --db=url",
    )
    args = parser.parse_args()

    url = DB_ALIASES.get(args.db) or args.url
    if not url:
        parser.error("--url is required with --db=url")

    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("MQTT_BROKER_HOST", "127.0.0.1")
    os.environ.setdefault("MQTT_BROKER_PORT", "1886")

    from app.database import SessionLocal, create_tables, drop_all
    from app.services.seed import seed

    print(f"[reset] dropping schema at {url}")
    drop_all()
    create_tables()

    with SessionLocal() as db:
        seed(db, seed_demo_user=False)
    print("[reset] config-only seed applied (faculties/stations/routing/counter).")
    print("[reset] NO demo user created; leaderboard activistic from real deposits only.")


if __name__ == "__main__":
    main()