"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _create_engine(url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        # FastAPI runs sync dependencies in a thread pool.
        connect_args["check_same_thread"] = False
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_engine() -> Engine:
    """Engine for application reads and writes."""
    return _create_engine(get_settings().database_url)


@lru_cache
def get_query_engine() -> Engine:
    """Engine for executing LLM-generated SQL.

    Uses QUERY_DATABASE_URL when set so generated queries can run as a
    least-privilege, read-only role.
    """
    url = get_settings().query_database_url
    return _create_engine(url) if url else get_engine()


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
