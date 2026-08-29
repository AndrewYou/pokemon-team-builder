"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _connect_args() -> dict[str, Any]:
    # asyncpg takes TLS as a connect arg, not a URL query param. Neon terminates
    # any connection that does not negotiate TLS, so this is load-bearing in prod.
    return {"ssl": "require"} if settings.database_requires_tls else {}


engine: AsyncEngine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    connect_args=_connect_args(),
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        yield session
