"""Type chart derivation and health reporting."""

from __future__ import annotations

import logging
import time

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.derived import registry
from api.derived.typechart import LEGAL_CHART_VALUES
from api.ingest import normalize
from api.ingest.client import RateLimitedClient
from api.ingest.sources import build_source
from api.models import Pokemon, TypeChart
from api.schemas import (
    CacheRebuildResponse,
    DerivedCacheHealth,
    DeriveTypesResponse,
    TypeChartHealth,
)

logger = logging.getLogger(__name__)

EXPECTED_ROWS = normalize.EXPECTED_TYPE_CHART_ROWS


async def derive_type_chart(session: AsyncSession, source_name: str) -> DeriveTypesResponse:
    """Parse damage_relations from the type payloads and write all 324 rows.

    PokeAPI lists only the exceptions, so every unlisted pairing is filled with
    1.0 by `normalize.type_chart_rows`. Writing the complete matrix means a
    lookup can never miss and fall back to a guess.
    """
    if source_name == "live":
        async with RateLimitedClient(
            settings.pokeapi_base_url,
            concurrency=settings.pokeapi_concurrency,
            batch_delay=settings.pokeapi_batch_delay,
        ) as client:
            result = await build_source(source_name, client).fetch_types()
    else:
        result = await build_source(source_name).fetch_types()

    rows = normalize.type_chart_rows(result.items)
    # Asserts both the 324-row count and the exact multiplier distribution,
    # raising TypeChartValidationError rather than writing a plausible-but-wrong
    # chart that nothing downstream would flag.
    distribution = normalize.validate_type_chart(rows)

    statement = insert(TypeChart).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["attacking_type", "defending_type"],
            set_={"multiplier": statement.excluded.multiplier},
        )
    )
    await session.commit()

    # The chart changed underneath the derived layer, so every defensive vector
    # computed from it is now wrong. Rebuild immediately rather than leaving the
    # cache invalid and the endpoints answering 503 until someone notices.
    try:
        await registry.rebuild(session)
    except Exception:
        # Unbuilt is recoverable and says so; stale is silently wrong.
        registry.invalidate()
        logger.exception("Derived cache rebuild failed after deriving the type chart")

    return DeriveTypesResponse(
        source=source_name,
        rows_written=len(rows),
        multiplier_distribution=distribution,
        all_values_legal=all(float(row["multiplier"]) in LEGAL_CHART_VALUES for row in rows),
    )


async def type_chart_health(session: AsyncSession) -> TypeChartHealth:
    """Distribution and legality of the stored chart, read live."""
    rows = (
        await session.execute(
            select(TypeChart.multiplier, func.count()).group_by(TypeChart.multiplier)
        )
    ).all()

    distribution = {normalize.format_multiplier(float(value)): int(count) for value, count in rows}
    total = sum(distribution.values())
    return TypeChartHealth(
        rows=total,
        expected_rows=EXPECTED_ROWS,
        complete=total == EXPECTED_ROWS,
        multiplier_distribution=dict(sorted(distribution.items(), key=lambda kv: float(kv[0]))),
        all_values_legal=all(float(value) in LEGAL_CHART_VALUES for value, _ in rows),
    )


def derived_cache_health() -> DerivedCacheHealth:
    """Status of the in-memory derived layer, without building it."""
    cache = registry.peek()
    if cache is None:
        return DerivedCacheHealth(
            built=False,
            pokemon_count=0,
            built_at=None,
            build_ms=None,
            illegal_vector_values=0,
            chart_complete=False,
        )
    return DerivedCacheHealth(
        built=True,
        pokemon_count=cache.pokemon_count,
        built_at=cache.built_at,
        build_ms=round(cache.build_ms, 2),
        illegal_vector_values=cache.illegal_value_count(),
        chart_complete=cache.chart_complete,
    )


async def rebuild_cache(session: AsyncSession) -> CacheRebuildResponse:
    """Rebuild the derived layer and report how long it took."""
    started = time.perf_counter()
    cache = await registry.rebuild(session)
    total_ms = (time.perf_counter() - started) * 1000

    chart_entries = sum(len(row) for row in cache.chart.values())
    return CacheRebuildResponse(
        pokemon_count=cache.pokemon_count,
        type_chart_entries=chart_entries,
        vector_shape=list(cache.vectors.shape),
        build_ms=round(cache.build_ms, 2),
        total_ms=round(total_ms, 2),
        built_at=cache.built_at,
    )


async def pokemon_types(
    session: AsyncSession, pokemon_id: int
) -> tuple[str, str, str | None] | None:
    """(name, type1, type2) for one Pokemon, or None if it does not exist."""
    row = (
        await session.execute(
            select(Pokemon.name, Pokemon.type1, Pokemon.type2).where(Pokemon.id == pokemon_id)
        )
    ).first()
    if row is None:
        return None
    return row.name, row.type1, row.type2
