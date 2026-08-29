"""Seed Postgres from a PokemonSource.

Run with `python -m api.ingest.seed`, or via `make seed` / `make seed-live`.

Idempotent by construction: every write is an upsert keyed on the natural
primary key, so re-running converges rather than duplicating or failing.

On failure handling -- this script never reports success it did not achieve.
Fetch failures and per-record normalisation errors are collected, printed in
full, and turned into a non-zero exit code. A seed that quietly dropped a third
of its movepools would look identical to a good one until the counter-team
endpoint had nothing to pick from, which is a debugging session nobody wants.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from tqdm import tqdm

from api.config import settings
from api.db import SessionLocal
from api.ingest import normalize
from api.ingest.client import FetchFailure, RateLimitedClient
from api.ingest.sources import FetchResult, PokemonSource, build_source
from api.models import (
    Move,
    Pokemon,
    PokemonAbility,
    PokemonMove,
    TypeChart,
)

# Postgres caps a statement at 65535 bind parameters. Chunk by column count so
# a wide table (pokemon, ~21 columns) and a narrow one (pokemon_move, 2) both
# stay comfortably inside the limit.
_MAX_BIND_PARAMS = 30_000

EXPECTED_TYPE_CHART_ROWS = len(normalize.CANONICAL_TYPES) ** 2


@dataclass(slots=True)
class RecordError:
    """A single record that could not be normalised."""

    entity: str
    identity: str
    error: str


@dataclass(slots=True)
class SeedReport:
    """Everything the run needs to say for itself."""

    counts: dict[str, int] = field(default_factory=dict)
    fetch_failures: list[FetchFailure] = field(default_factory=list)
    record_errors: list[RecordError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.fetch_failures and not self.record_errors


async def _upsert(
    session: AsyncSession,
    model: Any,
    rows: list[dict[str, Any]],
    *,
    index_elements: Sequence[str],
    update_columns: Sequence[str],
    desc: str,
) -> None:
    """Bulk upsert in chunks. No row-by-row inserts anywhere in this file."""
    if not rows:
        return

    chunk_size = max(1, _MAX_BIND_PARAMS // max(1, len(rows[0])))
    for start in tqdm(range(0, len(rows), chunk_size), desc=f"write {desc}", unit="chunk"):
        chunk = rows[start : start + chunk_size]
        statement = insert(model).values(chunk)
        if update_columns:
            statement = statement.on_conflict_do_update(
                index_elements=list(index_elements),
                set_={column: getattr(statement.excluded, column) for column in update_columns},
            )
        else:
            # Nothing to update: the row is entirely primary key.
            statement = statement.on_conflict_do_nothing(index_elements=list(index_elements))
        await session.execute(statement)


def _normalise_many(
    payloads: list[dict[str, Any]],
    entity: str,
    transform: Any,
    errors: list[RecordError],
) -> list[Any]:
    """Apply a transform to every payload, recording rather than hiding failures."""
    results: list[Any] = []
    for payload in payloads:
        identity = str(payload.get("name") or payload.get("id") or "<unknown>")
        try:
            results.append(transform(payload))
        except Exception as exc:  # noqa: BLE001 - recorded and surfaced, never swallowed
            errors.append(RecordError(entity=entity, identity=identity, error=repr(exc)))
    return results


async def seed(source: PokemonSource) -> SeedReport:
    """Fetch everything from `source` and upsert it into Postgres."""
    report = SeedReport()

    print(f"Seeding from source: {source.name}")
    types: FetchResult = await source.fetch_types()
    moves: FetchResult = await source.fetch_moves()
    pokemon: FetchResult = await source.fetch_pokemon()
    report.fetch_failures = [*types.failures, *moves.failures, *pokemon.failures]

    # The 18x18 chart is an invariant, not a best effort. A short chart means a
    # type failed to fetch, and silently storing 289 rows would produce wrong
    # effectiveness answers rather than an obvious error.
    type_rows = normalize.type_chart_rows(types.items)
    if len(type_rows) != EXPECTED_TYPE_CHART_ROWS:
        raise RuntimeError(
            f"type chart has {len(type_rows)} rows, expected {EXPECTED_TYPE_CHART_ROWS}"
        )

    move_rows = _normalise_many(moves.items, "move", normalize.move_row, report.record_errors)
    pokemon_rows = _normalise_many(
        pokemon.items, "pokemon", normalize.pokemon_row, report.record_errors
    )

    known_move_ids = {row["id"] for row in move_rows}
    ability_rows: list[dict[str, Any]] = []
    pokemon_move_rows: list[dict[str, Any]] = []
    for payload in pokemon.items:
        identity = str(payload.get("name") or payload.get("id") or "<unknown>")
        try:
            ability_rows.extend(normalize.pokemon_ability_rows(payload))
            pokemon_move_rows.extend(normalize.pokemon_move_rows(payload, known_move_ids))
        except Exception as exc:  # noqa: BLE001 - recorded and surfaced below
            report.record_errors.append(
                RecordError(entity="pokemon_relations", identity=identity, error=repr(exc))
            )

    async with SessionLocal() as session:
        await _upsert(
            session,
            TypeChart,
            type_rows,
            index_elements=["attacking_type", "defending_type"],
            update_columns=["multiplier"],
            desc="type_chart",
        )
        await _upsert(
            session,
            Move,
            move_rows,
            index_elements=["id"],
            update_columns=[
                "name",
                "type",
                "damage_class",
                "power",
                "accuracy",
                "priority",
                "effect_chance",
                "raw",
                "content_hash",
            ],
            desc="move",
        )
        await _upsert(
            session,
            Pokemon,
            pokemon_rows,
            index_elements=["id"],
            update_columns=[
                "name",
                "sprite_url",
                "type1",
                "type2",
                "base_hp",
                "base_atk",
                "base_def",
                "base_spatk",
                "base_spdef",
                "base_speed",
                "height",
                "weight",
                "is_default",
                "raw",
                "stats_hash",
                "types_hash",
                "moves_hash",
                "sprite_hash",
                "last_synced_at",
            ],
            desc="pokemon",
        )
        await _upsert(
            session,
            PokemonAbility,
            ability_rows,
            index_elements=["pokemon_id", "ability_name"],
            update_columns=["is_hidden"],
            desc="pokemon_ability",
        )
        await _upsert(
            session,
            PokemonMove,
            pokemon_move_rows,
            index_elements=["pokemon_id", "move_id"],
            update_columns=[],
            desc="pokemon_move",
        )
        await session.commit()

        for model in (Pokemon, Move, PokemonMove, PokemonAbility, TypeChart):
            total = await session.scalar(select(func.count()).select_from(model))
            report.counts[model.__tablename__] = int(total or 0)

    return report


def _print_summary(report: SeedReport) -> None:
    """Row counts as they stand in the database, not as we hoped they would."""
    width = max((len(name) for name in report.counts), default=10)
    print("\n" + "=" * (width + 12))
    print(f"{'table'.ljust(width)}  {'rows':>9}")
    print("-" * (width + 12))
    for table, count in report.counts.items():
        print(f"{table.ljust(width)}  {count:>9,}")
    print("=" * (width + 12))


def _print_failures(report: SeedReport) -> None:
    if report.fetch_failures:
        print(f"\n{len(report.fetch_failures)} fetch failure(s):", file=sys.stderr)
        for failure in report.fetch_failures:
            print(f"  {failure.url} -> {failure.error}", file=sys.stderr)
    if report.record_errors:
        print(f"\n{len(report.record_errors)} record error(s):", file=sys.stderr)
        for error in report.record_errors:
            print(f"  [{error.entity}] {error.identity} -> {error.error}", file=sys.stderr)


async def _run() -> int:
    source_name = settings.pokeapi_source
    if source_name.strip().lower() == "live":
        async with RateLimitedClient(
            settings.pokeapi_base_url,
            concurrency=settings.pokeapi_concurrency,
            batch_delay=settings.pokeapi_batch_delay,
        ) as client:
            report = await seed(build_source(source_name, client))
    else:
        report = await seed(build_source(source_name))

    _print_summary(report)
    _print_failures(report)

    if not report.ok:
        print("\nSeed completed WITH ERRORS -- see above. Exiting non-zero.", file=sys.stderr)
        return 1
    print("\nSeed completed successfully.")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
