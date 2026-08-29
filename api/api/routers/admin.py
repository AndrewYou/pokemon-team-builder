"""Admin operations. Thin: parse, delegate, return.

Every job here is startable and observable from Swagger, with no terminal.
"""

import enum
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.models import JobKind
from api.schemas import JobAccepted, JobRead, StatsResponse
from api.security import verify_admin
from api.services import jobs as job_service

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin)],
    responses={401: {"description": "Missing or invalid admin credentials."}},
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class SeedSource(enum.StrEnum):
    """Rendered as a dropdown in Swagger rather than a free-text field."""

    fixture = "fixture"
    live = "live"


@router.post(
    "/seed",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
    summary="Start a seed job",
    description=(
        "Loads Pokemon, moves, and the type chart into Postgres.\n\n"
        "`fixture` (default) reads the committed snapshot and finishes in seconds. "
        "`live` crawls pokeapi.co and takes minutes.\n\n"
        "Returns 202 immediately; poll the returned `poll_url` for progress. "
        "Returns 409 if a seed is already running."
    ),
    responses={409: {"description": "A seed job is already running."}},
)
async def start_seed(
    background: BackgroundTasks,
    session: SessionDep,
    source: Annotated[
        SeedSource, Query(description="Where to read data from.")
    ] = SeedSource.fixture,
) -> JobAccepted:
    try:
        job = await job_service.create_job(session, JobKind.seed)
    except job_service.JobAlreadyRunning as exc:
        # 409 rather than starting a second crawl over the same data.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    background.add_task(job_service.run_seed_job, job.id, source.value)
    return JobAccepted(job_id=job.id, status=job.status.value, poll_url=f"/admin/jobs/{job.id}")


@router.get(
    "/jobs",
    response_model=list[JobRead],
    summary="List recent jobs",
    description="Most recent first. Poll this while a seed runs to watch it progress.",
)
async def list_jobs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum jobs to return.")] = 50,
) -> list[JobRead]:
    return [JobRead.model_validate(job) for job in await job_service.list_jobs(session, limit)]


@router.get(
    "/jobs/{job_id}",
    response_model=JobRead,
    summary="Get one job",
    description="Full state of a single job, including row counts or the failure text.",
    responses={404: {"description": "No job with that id."}},
)
async def get_job(job_id: uuid.UUID, session: SessionDep) -> JobRead:
    job = await job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobRead.model_validate(job)


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Live row counts and data quality",
    description=(
        "Counts every table straight from the database. Re-run it while a seed "
        "is in flight to watch the tables fill up.\n\n"
        "Also reports the checks that catch a seed which technically succeeded "
        "but is unusable, such as a Pokemon with no sprite, which renders as a "
        "blank tile in the catalog grid."
    ),
)
async def get_stats(session: SessionDep) -> StatsResponse:
    return await job_service.collect_stats(session)
