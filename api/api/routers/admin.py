"""Admin operations. Thin: parse, delegate, return.

Every job here is startable and observable from Swagger, with no terminal.
"""

import enum
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.derived import registry
from api.derived.typechart import TYPE_INDEX, defensive_multiplier, explain, matchup
from api.models import JobKind
from api.schemas import (
    CacheRebuildResponse,
    DeriveTypesResponse,
    JobAccepted,
    JobRead,
    MatchupResponse,
    StatsResponse,
    TypeName,
    VectorResponse,
)
from api.security import verify_admin
from api.services import derive as derive_service
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


def _require_cache() -> registry.DerivedCache:
    """Fetch the derived cache or explain how to build it.

    503 rather than 500: an unbuilt cache is a missing precondition on a fresh
    deployment, not a bug, and the message says exactly which two calls fix it.
    """
    try:
        cache = registry.get_cache()
    except registry.DerivedCacheUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if not cache.chart_complete:
        # An incomplete chart defaults every missing pairing to 1.0, so serving
        # from it would return confident, neutral, wrong answers rather than
        # failing. Refuse instead.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Type chart is incomplete ({cache.chart_rows_loaded} of "
                f"{len(TYPE_INDEX) ** 2} pairings loaded). Run POST /admin/derive-types, "
                "then POST /admin/cache/rebuild."
            ),
        )
    return cache


@router.post(
    "/derive-types",
    response_model=DeriveTypesResponse,
    summary="Write the 324-row type chart",
    description=(
        "Parses `damage_relations` from the 18 type payloads and writes every "
        "attacking/defending pairing.\n\n"
        "PokeAPI lists only the exceptions, so unlisted pairings are filled with "
        "1.0 rather than left missing: a complete matrix means a lookup can never "
        "miss and silently fall back to a guess.\n\n"
        "Invalidates the derived cache, since the effectiveness data changed "
        "underneath it."
    ),
)
async def derive_types(
    session: SessionDep,
    source: Annotated[
        SeedSource, Query(description="Where to read the type payloads from.")
    ] = SeedSource.fixture,
) -> DeriveTypesResponse:
    try:
        return await derive_service.derive_type_chart(session, source.value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/cache/rebuild",
    response_model=CacheRebuildResponse,
    summary="Rebuild the derived caches",
    description=(
        "Reloads the type chart and recomputes every defensive vector, returning "
        "how long it took. Run this after a seed or a type-chart write."
    ),
)
async def rebuild_cache(session: SessionDep) -> CacheRebuildResponse:
    return await derive_service.rebuild_cache(session)


@router.get(
    "/debug/matchup",
    response_model=MatchupResponse,
    summary="Explain one attacking type against one Pokemon",
    description=(
        "Shows the derivation rather than just the answer, so a surprising number "
        "can be traced to the two components that produced it.\n\n"
        "Try `attacking_type=rock`, `pokemon_id=6`: Charizard is fire/flying, and "
        "rock is super effective against both, so 2 x 2 = 4."
    ),
    responses={404: {"description": "No Pokemon with that id."}},
)
async def debug_matchup(
    session: SessionDep,
    attacking_type: Annotated[TypeName, Query(description="The attacking type.")],
    pokemon_id: Annotated[int, Query(ge=1, description="Defending Pokemon.")],
) -> MatchupResponse:
    cache = _require_cache()
    found = await derive_service.pokemon_types(session, pokemon_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pokemon not found")
    name, type1, type2 = found

    attacking = attacking_type.value
    return MatchupResponse(
        pokemon_id=pokemon_id,
        pokemon_name=name,
        attacking_type=attacking,
        multiplier=defensive_multiplier(cache.chart, attacking, type1, type2),
        type1_component=matchup(cache.chart, attacking, type1),
        type2_component=matchup(cache.chart, attacking, type2) if type2 else None,
        explanation=explain(cache.chart, attacking, type1, type2),
    )


@router.get(
    "/debug/vector/{pokemon_id}",
    response_model=VectorResponse,
    summary="All 18 defensive multipliers for one Pokemon",
    description=(
        "The row this Pokemon occupies in the defensive matrix, with dual typing "
        "already multiplied in."
    ),
    responses={404: {"description": "No Pokemon with that id."}},
)
async def debug_vector(pokemon_id: int, session: SessionDep) -> VectorResponse:
    cache = _require_cache()
    found = await derive_service.pokemon_types(session, pokemon_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pokemon not found")
    name, type1, type2 = found

    try:
        multipliers = cache.vector_as_dict(pokemon_id)
    except KeyError as exc:
        # In the database but not in the cache: the cache predates the seed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pokemon is not in the derived cache. Run POST /admin/cache/rebuild.",
        ) from exc

    return VectorResponse(
        pokemon_id=pokemon_id,
        pokemon_name=name,
        types=[t for t in (type1, type2) if t],
        multipliers=multipliers,
    )
