"""
Database bootstrap (Phase 12) — SQLAlchemy 2.x over SQLite.

One engine, one session factory, one FastAPI dependency. SQLite is configured
for multi-threaded FastAPI use (check_same_thread=False) with WAL journaling
so reads don't block writes.

Schema management is Alembic's job (backend/alembic/). `init_db()` also runs
`create_all` at startup as a dev-friendly safety net — it is a no-op when the
tables already exist, and it means a fresh clone works even before the first
`alembic upgrade head`.
"""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base every ORM model inherits from."""


engine = create_engine(
    settings.DATABASE_URL,
    # FastAPI serves requests from a threadpool; SQLite connections must be
    # allowed to hop threads (SQLAlchemy's pool still serializes access).
    connect_args=(
        {"check_same_thread": False}
        if settings.DATABASE_URL.startswith("sqlite")
        else {}
    ),
)

if settings.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover
        """WAL for concurrent reads + enforced foreign keys on every connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one Session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create any missing tables (idempotent dev safety net; Alembic owns prod)."""
    # Import registers the models on Base.metadata before create_all.
    from app.infrastructure.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database ready at %s", settings.DATABASE_URL)
