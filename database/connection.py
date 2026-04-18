"""
database/connection.py
──────────────────────
SQLAlchemy engine + session factory.

Reads DATABASE_URL from config/settings.py.
Defaults to SQLite (algobot.db) so the bot works out-of-the-box
with zero extra setup.  Swap to PostgreSQL by setting the env var:

    DATABASE_URL=postgresql+psycopg2://user:pass@localhost/algobot

Usage
-----
    from database.connection import get_session, engine

    with get_session() as session:
        session.add(some_model)
        session.commit()
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


# ── Engine ────────────────────────────────────────────────────────────────────

def _build_engine():
    url = settings.DATABASE_URL
    kwargs: dict = {}

    if url.startswith("sqlite"):
        # SQLite needs check_same_thread=False for FastAPI's multi-thread env
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["pool_pre_ping"] = True
    else:
        # PostgreSQL / MySQL — use a small connection pool
        kwargs["pool_size"]    = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_pre_ping"] = True

    engine = create_engine(url, **kwargs)

    # Enable WAL mode for SQLite (better concurrent reads)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    logger.info("Database engine created: %s", url.split("@")[-1])   # hide credentials
    return engine


engine = _build_engine()

# ── Session factory ───────────────────────────────────────────────────────────

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,   # keep objects usable after session closes
)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context-manager that yields a transactional session.
    Commits on clean exit, rolls back on exception.

    Example::

        with get_session() as session:
            session.add(Trade(...))
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Health check ──────────────────────────────────────────────────────────────

def check_connection() -> bool:
    """Return True if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database connection check failed: %s", exc)
        return False
