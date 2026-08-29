"""Background job orchestration.

The HTTP layer records a job, hands the work to a background task, and answers
202. Everything about a running job is observable through the job row, because
the demo surface is a browser and there is no terminal to watch.
"""

from __future__ import annotations

import datetime
import logging
import traceback
import uuid
from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.db import SessionLocal
from api.derived import registry
from api.ingest.client import RateLimitedClient
from api.ingest.seed import seed
from api.ingest.sources import build_source
from api.models import (
    ACTIVE_STATUSES,
    AppUser,
    ChangeAck,
    DataChange,
    Job,
    JobStatus,
    Move,
    Pokemon,
    PokemonAbility,
    PokemonMove,
    SyncRun,
    Team,
    TeamMember,
    TypeChart,
)
from api.schemas import DataQuality, StatsResponse
from api.services import derive as derive_service

# Order chosen to read top-down in the Swagger response: reference data first,
# then user data, then operational tables.
_COUNTED_MODELS = (
    Pokemon,
    Move,
    PokemonMove,
    PokemonAbility,
    TypeChart,
    AppUser,
    Team,
    TeamMember,
    SyncRun,
    DataChange,
    ChangeAck,
    Job,
)


logger = logging.getLogger(__name__)


class JobAlreadyRunning(Exception):
    """A job of this kind is already pending or running."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"A {kind} job is already running")
        self.kind = kind


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def create_job(session: AsyncSession, kind: str) -> Job:
    """Create a pending job, refusing if one of the same kind is already active.

    Checked twice on purpose. The query catches the common case with a clear
    error; the partial unique index catches the race where two requests both
    pass that check and would otherwise start duplicate crawls.
    """
    existing = await session.scalar(
        select(Job.id).where(Job.kind == kind, Job.status.in_(ACTIVE_STATUSES)).limit(1)
    )
    if existing is not None:
        raise JobAlreadyRunning(kind)

    job = Job(kind=kind, status=JobStatus.pending)
    session.add(job)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise JobAlreadyRunning(kind) from exc
    await session.refresh(job)
    return job


async def list_jobs(session: AsyncSession, limit: int = 50) -> list[Job]:
    """Most recent jobs first."""
    result = await session.scalars(select(Job).order_by(desc(Job.created_at)).limit(limit))
    return list(result)


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
    return await session.get(Job, job_id)


async def _set_job(job_id: uuid.UUID, **values: Any) -> None:
    """Update a job in its own session.

    The request's session is long gone by the time the background task runs, so
    every write here opens and closes its own.
    """
    async with SessionLocal() as session:
        await session.execute(update(Job).where(Job.id == job_id).values(**values))
        await session.commit()


async def run_seed_job(job_id: uuid.UUID, source_name: str) -> None:
    """Background entry point for POST /admin/seed.

    Never raises: a background task that dies takes its stack trace with it, so
    the failure is written to the job row instead, which is the only place the
    reviewer can see it.
    """
    await _set_job(job_id, status=JobStatus.running, started_at=_utcnow(), detail="starting")

    async def progress(message: str) -> None:
        await _set_job(job_id, detail=message)

    try:
        if source_name == "live":
            async with RateLimitedClient(
                settings.pokeapi_base_url,
                concurrency=settings.pokeapi_concurrency,
                batch_delay=settings.pokeapi_batch_delay,
            ) as client:
                report = await seed(build_source(source_name, client), on_progress=progress)
        else:
            report = await seed(build_source(source_name), on_progress=progress)
    except Exception:
        await _set_job(
            job_id,
            status=JobStatus.failed,
            finished_at=_utcnow(),
            detail="failed",
            error=traceback.format_exc(),
        )
        return

    # Reference data just changed, so the derived layer describes the old data.
    # Rebuilding here rather than leaving it to the operator: the defensive
    # vectors are precomputed, so a stale cache does not fail, it answers
    # confidently wrong -- a Pokemon whose types changed keeps its old
    # multipliers while reporting its new types in the same response.
    await progress("rebuilding derived cache")
    try:
        async with SessionLocal() as session:
            await registry.rebuild(session)
    except Exception:
        # Never leave a stale cache serving. Unbuilt answers 503 with
        # instructions, which is recoverable; stale is silently wrong.
        registry.invalidate()
        logger.exception("Derived cache rebuild failed after seed")

    if report.ok:
        await _set_job(
            job_id,
            status=JobStatus.succeeded,
            finished_at=_utcnow(),
            detail="done",
            result=report.counts,
        )
        return

    # Partially successful is not successful. Same rule as the CLI's exit code:
    # a seed missing a third of its movepools must not report success.
    problems = [f"{f.url} -> {f.error}" for f in report.fetch_failures]
    problems += [f"[{e.entity}] {e.identity} -> {e.error}" for e in report.record_errors]
    await _set_job(
        job_id,
        status=JobStatus.failed,
        finished_at=_utcnow(),
        detail="completed with errors",
        result=report.counts,
        error="\n".join(problems),
    )


async def collect_stats(session: AsyncSession) -> StatsResponse:
    """Live row counts plus the checks that catch an unusable seed."""
    counts: dict[str, int] = {}
    for model in _COUNTED_MODELS:
        total = await session.scalar(select(func.count()).select_from(model))
        counts[model.__tablename__] = int(total or 0)

    missing_sprite_or_type = await session.scalar(
        select(func.count())
        .select_from(Pokemon)
        .where((Pokemon.sprite_url.is_(None)) | (Pokemon.type1.is_(None)))
    )
    missing_raw = await session.scalar(
        select(func.count()).select_from(Pokemon).where(Pokemon.raw.is_(None))
    )

    quality = DataQuality(
        pokemon_missing_sprite_or_type=int(missing_sprite_or_type or 0),
        pokemon_missing_raw=int(missing_raw or 0),
        ok=not (missing_sprite_or_type or missing_raw),
    )
    return StatsResponse(
        counts=counts,
        data_quality=quality,
        type_chart=await derive_service.type_chart_health(session),
        derived=derive_service.derived_cache_health(),
    )
