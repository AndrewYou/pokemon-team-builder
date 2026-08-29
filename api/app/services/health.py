"""Health-check business logic."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import HealthResponse

logger = logging.getLogger(__name__)


async def check_health(session: AsyncSession) -> HealthResponse:
    """Probe the database with a trivial query.

    A failure is reported in the body rather than raised, so the endpoint always
    answers 200. That keeps the platform health check green while the frontend
    can still surface *why* the database is unreachable.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database health check failed")
        return HealthResponse(ok=False, db=f"error: {type(exc).__name__}")
    return HealthResponse(ok=True, db="connected")
