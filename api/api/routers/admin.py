"""Admin operations. Thin: parse, delegate, return.

Every job here is startable and observable from Swagger, with no terminal.
"""

import enum
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.counterteam import scoring
from api.db import get_session
from api.derived import registry
from api.derived.typechart import TYPE_INDEX, defensive_multiplier, explain, matchup
from api.models import JobKind
from api.schemas import (
    AgedChangeResponse,
    CacheRebuildResponse,
    ChangeRead,
    DeriveTypesResponse,
    DeterminismCheckResponse,
    DriftResponse,
    ExplainResponse,
    JobAccepted,
    JobRead,
    MatchupDetail,
    MatchupResponse,
    NormalizeDebugResponse,
    ResetDemoResponse,
    SimulateChangeRequest,
    SimulateChangeResponse,
    StatsResponse,
    SyncRunRead,
    TypeName,
    VectorResponse,
    error_response,
)
from api.security import ADMIN_UNAUTHORIZED_DETAIL, verify_admin
from api.services import alerts as alert_service
from api.services import derive as derive_service
from api.services import explain as explain_service
from api.services import jobs as job_service
from api.services import normalization as normalization_service
from api.services import sync_service

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin)],
    responses={
        401: error_response(
            "Missing or invalid admin credentials. Defaults are admin / pokemon.",
            ADMIN_UNAUTHORIZED_DETAIL,
        )
    },
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
    responses={
        409: error_response(
            "A seed is already in flight. Poll its job rather than starting a second one.",
            "A seed job is already running",
        )
    },
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
    responses={404: error_response("No job with that id.", "Job not found")},
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


def require_cache() -> registry.DerivedCache:
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
    responses={
        422: error_response(
            "The parsed chart does not match the known one, so it was not stored.",
            "multiplier distribution {'0': 8, '0.5': 60, '1': 204, '2': 52} does not match "
            "the known chart {'0': 8, '0.5': 61, '1': 204, '2': 51}. A mismatch usually "
            "means past_damage_relations was read instead of damage_relations.",
        )
    },
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
    responses={
        404: error_response("No Pokemon with that id.", "Pokemon not found"),
        503: error_response(
            "The derived cache is not built, or the type chart is incomplete.",
            registry.CACHE_UNAVAILABLE_DETAIL,
        ),
    },
)
async def debug_matchup(
    session: SessionDep,
    attacking_type: Annotated[TypeName, Query(description="The attacking type.")],
    pokemon_id: Annotated[int, Query(ge=1, description="Defending Pokemon.")],
) -> MatchupResponse:
    cache = require_cache()
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
    responses={
        404: error_response("No Pokemon with that id.", "Pokemon not found"),
        503: error_response(
            "The derived cache is not built, or the type chart is incomplete.",
            registry.CACHE_UNAVAILABLE_DETAIL,
        ),
    },
)
async def debug_vector(pokemon_id: int, session: SessionDep) -> VectorResponse:
    cache = require_cache()
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


@router.get(
    "/debug/normalize/{pokemon_id}",
    response_model=NormalizeDebugResponse,
    summary="Show a payload beside its normalised projection",
    description=(
        "Normalisation projects a raw payload down to the fields we actually "
        "consume and orders every array deterministically. Without it, hashing "
        "reports a change on every run: PokeAPI does not guarantee array "
        "ordering, and most of the payload is data we never read.\n\n"
        "`dropped_fields` lists exactly what was discarded, and `hashes_match` "
        "compares a fresh computation against what the database stored."
    ),
    responses={404: error_response("No Pokemon with that id.", "Pokemon not found")},
)
async def debug_normalize(pokemon_id: int, session: SessionDep) -> NormalizeDebugResponse:
    result = await normalization_service.normalize_debug(session, pokemon_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pokemon not found")
    return result


@router.post(
    "/debug/determinism-check",
    response_model=DeterminismCheckResponse,
    summary="Re-hash every stored Pokemon and compare",
    description=(
        "Re-normalises and re-hashes every stored Pokemon, comparing against the "
        "hashes already in the database.\n\n"
        "This is the check that protects the change-detection demo. If "
        "normalisation is not a pure function of the stored payload, the next "
        "sync reports every Pokemon as changed and the feed becomes noise. "
        "Any result above zero mismatches is a bug, not a data change."
    ),
)
async def debug_determinism_check(session: SessionDep) -> DeterminismCheckResponse:
    return await normalization_service.determinism_check(session)


@router.get(
    "/debug/explain",
    response_model=ExplainResponse,
    summary="Show the query plan for a catalog query",
    description=(
        "Runs EXPLAIN (ANALYZE, BUFFERS) on the query the application actually "
        "issues, so index usage is checkable from the browser rather than "
        "asserted in a comment.\n\n"
        "`name_search` is the one to watch: the prefix search is served by a "
        "`text_pattern_ops` index, and a sequential scan here means something "
        "changed the query into a shape the index cannot serve."
    ),
)
async def debug_explain(
    session: SessionDep,
    query: Annotated[
        explain_service.ExplainQuery, Query(description="Which query to explain.")
    ] = explain_service.ExplainQuery.name_search,
) -> ExplainResponse:
    sql, plan = await explain_service.explain(session, query)
    return ExplainResponse(
        query=query.value,
        sql=sql,
        plan=plan,
        uses_index=any("Index Scan" in line or "Index Only Scan" in line for line in plan),
    )


@router.get(
    "/changes",
    response_model=list[ChangeRead],
    summary="Recent detected changes",
    description=(
        "Field-level changes found by past syncs, newest first, rendered as the "
        "sentences a user would see.\n\n"
        "`old_value` is what our snapshot held before the sync and `new_value` is "
        "what upstream reports now."
    ),
)
async def list_changes(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[ChangeRead]:
    return await sync_service.list_changes(session, limit)


@router.get(
    "/drift",
    response_model=DriftResponse,
    summary="What a sync would find right now",
    description=(
        "Stored rows whose section hashes no longer match the reference snapshot, "
        "so you can see what is outstanding before running a sync.\n\n"
        "Compared against the committed fixture rather than a live fetch, which "
        "keeps this a fast read instead of a few thousand HTTP requests.\n\n"
        "There is no reset endpoint because none is needed: a sync restores the "
        "true upstream values, so running one clears the drift."
    ),
)
async def get_drift(session: SessionDep) -> DriftResponse:
    return await sync_service.drift(session)


@router.post(
    "/simulate-change",
    response_model=SimulateChangeResponse,
    summary="Diverge our snapshot so detection is demonstrable",
    description=(
        "**This mutates OUR SNAPSHOT, not PokeAPI.** Upstream is read-only to us "
        "and is untouched. This edits the copy in our own database so the next "
        "sync has something real to find.\n\n"
        "**Note the inversion.** If a Pokemon's Attack is 55 upstream and this "
        "changes our copy to 71, the sync sees 71 -> 55: `old_value` is what we "
        "mutated to and `new_value` is the true upstream value. This catches "
        "people out every time.\n\n"
        "Every field is optional. Omit `pokemon_ids` to pick `count` at random; "
        "omit `fields` for one random group each. Listing several fields mutates "
        "**every** listed group on **every** named Pokemon, so "
        '`["stats","types","sprite"]` on 2 Pokemon with '
        "`mutations_per_field: 2` yields 2 stat + 2 type + 1 sprite changes each "
        "(sprite has a single value, so it caps at 1) -- 10 in total.\n\n"
        "Each discrete change becomes its own `data_change` row, so "
        "`total_mutations` is exactly what `GET /admin/changes` returns after the "
        "next sync. `expect_alert` is the literal alert text to compare against "
        "the UI.\n\n"
        "No reset endpoint is needed: the sync restores the true values."
    ),
    responses={
        422: error_response(
            "One or more requested Pokemon do not exist.",
            "Unknown Pokemon ids: [99999].",
        )
    },
)
async def simulate_change(
    payload: SimulateChangeRequest, session: SessionDep
) -> SimulateChangeResponse:
    try:
        return await sync_service.simulate_change(session, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get(
    "/sync-runs",
    response_model=list[SyncRunRead],
    summary="Change-detection run history",
    description=(
        "Every sync, newest first, with what it scanned and what it found.\n\n"
        "A run recording 1025 records scanned and **0 changes found** is the point "
        "of this log: it shows the detector checked everything and reported "
        "nothing, which is what separates it from a notification generator. Both "
        "outcomes appear in the response examples.\n\n"
        "`GET /admin/changes` has the field-level detail behind any run that found "
        "something."
    ),
)
async def list_sync_runs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SyncRunRead]:
    return await sync_service.list_sync_runs(session, limit)


@router.post(
    "/reset-demo",
    response_model=ResetDemoResponse,
    summary="Clear change-detection history (DESTRUCTIVE, demo only)",
    description=(
        "**Destructive. Demo hygiene only.** Permanently deletes every row from "
        "`change_ack`, `data_change`, and `sync_run`, in one transaction, so the "
        "change-detection sequence can be rehearsed repeatedly without earlier "
        "runs accumulating as noise. There is no undo.\n\n"
        "**Teams are never deleted.** `team` and `team_member` are untouched "
        "regardless of parameters -- a reset that wiped the roster you just built "
        "would make the demo useless.\n\n"
        "`restore_snapshot=true` additionally runs a fixture seed, which clears any "
        "outstanding `simulate-change` drift in the same call. A seed rather than a "
        "sync on purpose: a sync would restore the values but write a fresh "
        "`sync_run` and a `data_change` for every repair, which is exactly the "
        "noise this endpoint removes.\n\n"
        "Rows are deleted rather than truncated. `TRUNCATE` does not follow "
        "`ON DELETE CASCADE` and refuses while `change_ack` references "
        "`data_change`; `DELETE` honours the cascade and reports how many rows it "
        "removed."
    ),
    responses={
        422: error_response(
            "keep_teams=false was requested. Teams are never deleted by this endpoint.",
            "Teams are never deleted by this endpoint; omit keep_teams or pass true.",
        )
    },
)
async def reset_demo(
    session: SessionDep,
    restore_snapshot: Annotated[
        bool,
        Query(description="Also run a fixture seed, clearing any outstanding drift."),
    ] = False,
    keep_teams: Annotated[
        bool,
        Query(
            description=(
                "Always true. Accepted so the guarantee is visible here rather than "
                "buried in prose; passing false is rejected rather than silently ignored."
            )
        ),
    ] = True,
) -> ResetDemoResponse:
    if not keep_teams:
        # Refusing beats quietly doing something other than what was asked.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Teams are never deleted by this endpoint; omit keep_teams or pass true.",
        )
    return await sync_service.reset_demo(session, restore_snapshot=restore_snapshot)


@router.post(
    "/age-change/{change_id}",
    response_model=AgedChangeResponse,
    summary="Backdate a change so the alert window is demonstrable",
    description=(
        "Moves a change's `detected_at` backwards so it falls outside the "
        f"{alert_service.WINDOW_DAYS}-day window `GET /alerts` looks at.\n\n"
        "Demo affordance only. Without it, showing that old changes drop out of "
        "the feed would mean waiting a week. Age a change past the window and it "
        "disappears from /alerts while remaining in /admin/changes, which is the "
        "distinction between what is news and what is history."
    ),
    responses={404: error_response("No change with that id.", "Change not found")},
)
async def age_change(
    change_id: int,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=3650, description="How many days to move it back.")] = 8,
) -> AgedChangeResponse:
    result = await alert_service.age_change(session, change_id, days)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")
    return result


@router.get(
    "/debug/matchup-detail",
    response_model=MatchupDetail,
    summary="Every number behind one pairing",
    description=(
        "The full damage breakdown for one attacker against one defender: the "
        "move chosen from the collapsed movepool, both stats used, the "
        "multiplier and STAB, the raw damage, the continuous fraction the "
        "scorer works on, the rounded turn count shown to users, and the speed "
        "comparison.\n\n"
        "Try `attacker=248&defender=6` -- Tyranitar's rock move is 4x into "
        "Charizard's fire/flying."
    ),
    responses={
        404: error_response("No Pokemon with that id.", "Pokemon not found"),
        503: error_response(
            "The derived cache is not built, or the type chart is incomplete.",
            registry.CACHE_UNAVAILABLE_DETAIL,
        ),
    },
)
async def debug_matchup_detail(
    attacker: Annotated[int, Query(ge=1, description="Attacking Pokemon id.")],
    defender: Annotated[int, Query(ge=1, description="Defending Pokemon id.")],
) -> MatchupDetail:
    cache = require_cache()
    for pokemon_id in (attacker, defender):
        if pokemon_id not in cache.pokemon_index:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pokemon not found")
    return MatchupDetail(
        **scoring.explain_matchup(
            cache, cache.pokemon_index[attacker], cache.pokemon_index[defender]
        )
    )
