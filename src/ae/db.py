"""Database engine and session management."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ae.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None
_redis_client = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.ae_database_url

        kwargs = {
            "echo": False,
        }

        if url.startswith("sqlite"):
            # SQLite specific settings
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            # PostgreSQL settings
            kwargs["pool_pre_ping"] = True
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10

        _engine = create_engine(url, **kwargs)

        # Enable WAL mode for SQLite for better concurrency
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_redis():
    """Get Redis client, or None if Redis is not configured."""
    global _redis_client
    settings = get_settings()

    if not settings.ae_redis_url:
        return None

    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(
                settings.ae_redis_url,
                decode_responses=True,
            )
            _redis_client.ping()
        except Exception as e:
            logger.warning("Redis not available: %s. Using in-memory cache.", e)
            return None

    return _redis_client


def init_db():
    """Create all tables (for development/SQLite)."""
    from ae.models import Base
    Base.metadata.create_all(get_engine())
    logger.info("Database tables created")
