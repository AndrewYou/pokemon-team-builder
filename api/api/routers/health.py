"""Health endpoint. Parse, delegate, return."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.schemas import HealthResponse
from api.services import health as health_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health(session: Annotated[AsyncSession, Depends(get_session)]) -> HealthResponse:
    return await health_service.check_health(session)
