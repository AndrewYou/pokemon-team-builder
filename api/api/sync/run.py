"""The change-detection sync job.

Compares what upstream reports now against the snapshot we hold, records every
field-level difference, and updates the snapshot.

Run with `python -m api.sync.run --source fixture`, or through
POST /admin/sync.

Two properties matter more than speed. The run is **resumable**: records are
committed in batches, so a fetch failure at record 800 keeps the findings from
the first 799 rather than rolling back a job that took minutes. And a run that
finds nothing is recorded just as carefully as one that finds something -- a
sync_run row saying 1025 records scanned and zero changes found is the evidence
that this is a detector rather than a notification generator.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.db import SessionLocal
from api.derived import registry
from api.ingest.client import FetchFailure, RateLimitedClient
from api.ingest.normalize import pokemon_row
from api.ingest.sources import PokemonSource, StaleSource, build_source
from api.models import DataChange, Move, Pokemon, PokemonMove, SyncRun, SyncSource
from api.sync.hashing import section_hashes
from api.sync.normalize import diff, normalize_pokemon

logger = logging.getLogger(__name__)

# Records are committed in groups of this size. Small enough that a failure
# loses little work, large enough not to make a sync a per-row round trip.
BATCH_SIZE = 100

ENTITY_POKEMON = "pokemon"

ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class SyncOutcome:
    """What a run did, mirroring the sync_run row it wrote."""

    sync_run_id: int
    source: str
    status: str
    records_scanned: int = 0
    changes_found: int = 0
    fetch_failures: list[FetchFailure] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def _stored_snapshot(session: AsyncSession) -> dict[int, dict[str, Any]]:
    """Everything we currently hold, keyed by id."""
    rows = (
        await session.execute(
            select(
                Pokemon.id,
                Pokemon.raw,
                Pokemon.stats_hash,
                Pokemon.types_hash,
                Pokemon.moves_hash,
                Pokemon.sprite_hash,
            )
        )
    ).all()
    return {
        row.id: {
            "raw": row.raw,
            "hashes": {
                "stats_hash": row.stats_hash,
                "types_hash": row.types_hash,
                "moves_hash": row.moves_hash,
                "sprite_hash": row.sprite_hash,
            },
        }
        for row in rows
    }


async def _reconcile_moves(session: AsyncSession, pokemon_id: int, payload: dict[str, Any]) -> None:
    """Rewrite the movepool join rows for one changed Pokemon.

    Without this the join table keeps whatever the previous snapshot said, so a
    movepool change would show in the alert feed but never in the catalog.
    """
    normalized = normalize_pokemon(payload)
    move_ids = list(normalized["moves"])
    await session.execute(delete(PokemonMove).where(PokemonMove.pokemon_id == pokemon_id))
    if not move_ids:
        return
    known = set((await session.scalars(select(Move.id).where(Move.id.in_(move_ids)))).all())
    session.add_all(
        [
            PokemonMove(pokemon_id=pokemon_id, move_id=move_id)
            for move_id in move_ids
            if move_id in known
        ]
    )


async def _apply_source(session: AsyncSession, source_name: str) -> PokemonSource:
    """Resolve the source, including the stale case that replays our own data."""
    if source_name == SyncSource.stale.value:
        stored = await _stored_snapshot(session)
        return StaleSource([entry["raw"] for entry in stored.values()])
    if source_name == SyncSource.live.value:
        client = RateLimitedClient(
            settings.pokeapi_base_url,
            concurrency=settings.pokeapi_concurrency,
            batch_delay=settings.pokeapi_batch_delay,
        )
        return build_source(source_name, client)
    return build_source(source_name)


async def run_sync(source_name: str, on_progress: ProgressCallback | None = None) -> SyncOutcome:
    """Run one sync and return what it found."""

    async def progress(message: str) -> None:
        if on_progress is not None:
            await on_progress(message)

    async with SessionLocal() as session:
        run = SyncRun(source=SyncSource(source_name), status="running")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    outcome = SyncOutcome(sync_run_id=run_id, source=source_name, status="running")

    try:
        await progress("fetching upstream data")
        async with SessionLocal() as session:
            source = await _apply_source(session, source_name)
            fetched = await source.fetch_pokemon()
        outcome.fetch_failures = list(fetched.failures)

        await progress("loading stored snapshot")
        async with SessionLocal() as session:
            stored = await _stored_snapshot(session)

        payloads = fetched.items
        for start in range(0, len(payloads), BATCH_SIZE):
            batch = payloads[start : start + BATCH_SIZE]
            await progress(
                f"comparing {start + 1}-{min(start + BATCH_SIZE, len(payloads))} of {len(payloads)}"
            )
            # Each batch is its own transaction, so an error part-way through a
            # long run keeps everything already found.
            async with SessionLocal() as session:
                scanned, found = await _process_batch(session, batch, stored, run_id)
                await session.commit()
            outcome.records_scanned += scanned
            outcome.changes_found += found

        outcome.status = "succeeded" if not outcome.fetch_failures else "completed_with_errors"

    except Exception as exc:
        logger.exception("Sync failed")
        outcome.status = "failed"
        outcome.error = f"{type(exc).__name__}: {exc}"

    async with SessionLocal() as session:
        await session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(
                finished_at=_utcnow(),
                records_scanned=outcome.records_scanned,
                changes_found=outcome.changes_found,
                status=outcome.status,
            )
        )
        await session.commit()

    if outcome.changes_found:
        # Reference data moved, so anything derived from it describes the old
        # data. Rebuilding here rather than only invalidating keeps the app
        # usable immediately after a sync.
        await progress("rebuilding derived caches")
        try:
            async with SessionLocal() as session:
                await registry.rebuild(session)
        except Exception:
            registry.invalidate()
            logger.exception("Derived cache rebuild failed after sync")

    logger.info(
        "Sync %s: source=%s scanned=%d changes=%d",
        outcome.status,
        source_name,
        outcome.records_scanned,
        outcome.changes_found,
    )
    return outcome


async def _process_batch(
    session: AsyncSession,
    batch: list[dict[str, Any]],
    stored: dict[int, dict[str, Any]],
    run_id: int,
) -> tuple[int, int]:
    """Compare one batch, writing changes and updated rows. Returns (scanned, found)."""
    scanned = 0
    found = 0
    scanned_ids: list[int] = []

    for payload in batch:
        pokemon_id = payload["id"]
        scanned += 1
        scanned_ids.append(pokemon_id)

        fresh_row = pokemon_row(payload)
        fresh_hashes = section_hashes(normalize_pokemon(payload))
        previous = stored.get(pokemon_id)

        if previous is None:
            # New upstream. Recorded as a change so the feed shows it, and
            # inserted so the snapshot stays complete.
            session.add(Pokemon(**fresh_row))
            session.add(
                DataChange(
                    sync_run_id=run_id,
                    entity_type=ENTITY_POKEMON,
                    entity_id=str(pokemon_id),
                    field_path="added",
                    old_value=None,
                    new_value=payload.get("name"),
                )
            )
            found += 1
            continue

        # The hash comparison is the gate; the diff is what produces the detail.
        if previous["hashes"] == fresh_hashes:
            continue

        changes = diff(previous["raw"], payload)
        for change in changes:
            session.add(
                DataChange(
                    sync_run_id=run_id,
                    entity_type=ENTITY_POKEMON,
                    entity_id=str(pokemon_id),
                    field_path=change.field_path,
                    old_value=change.old_value,
                    new_value=change.new_value,
                )
            )
        found += len(changes)

        await session.execute(
            update(Pokemon)
            .where(Pokemon.id == pokemon_id)
            .values(**fresh_row, last_synced_at=_utcnow())
        )
        await _reconcile_moves(session, pokemon_id, payload)

    if scanned_ids:
        # Every scanned row was confirmed against upstream, whether or not it
        # changed, so the timestamp reflects the check rather than the write.
        await session.execute(
            update(Pokemon).where(Pokemon.id.in_(scanned_ids)).values(last_synced_at=_utcnow())
        )

    return scanned, found


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Detect upstream changes against our snapshot.")
    parser.add_argument(
        "--source",
        choices=[s.value for s in SyncSource],
        default=settings.pokeapi_source,
        help="live hits pokeapi.co; fixture reads the committed snapshot; "
        "stale replays our own data and must find zero changes.",
    )
    args = parser.parse_args(argv)

    outcome = asyncio.run(run_sync(args.source))

    print(f"\nsync_run #{outcome.sync_run_id} [{outcome.status}] source={outcome.source}")
    print(f"  records scanned: {outcome.records_scanned:,}")
    print(f"  changes found:   {outcome.changes_found:,}")
    if outcome.fetch_failures:
        print(f"  fetch failures:  {len(outcome.fetch_failures)}", file=sys.stderr)
        for failure in outcome.fetch_failures[:10]:
            print(f"    {failure.url} -> {failure.error}", file=sys.stderr)
    if outcome.error:
        print(f"  error: {outcome.error}", file=sys.stderr)
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    sys.exit(main())
