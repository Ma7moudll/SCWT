"""SQLAlchemy engine / session wiring, portable across SQLite (tests) and
PostgreSQL (production via psycopg2). Alembic owns the schema in production;
tests create tables on the fly with `Base.metadata.create_all`.

The engine is created lazily from `settings.database_url` on first use so
tests can reconfigure the URL before any connection happens.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, orm
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from .config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = settings.database_url
        _engine = create_engine(url, **_engine_kwargs(url))
    return _engine


def reset_engine() -> None:
    """Test helper: drops the cached engine so a new URL takes effect."""
    global _engine
    _engine = None


_session_factory = orm.sessionmaker(bind=None, autoflush=False, expire_on_commit=False)


def SessionLocal() -> Session:
    return _session_factory(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    # Import models so the metadata is populated before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def drop_all() -> None:
    from . import models  # noqa: F401

    Base.metadata.drop_all(bind=get_engine())