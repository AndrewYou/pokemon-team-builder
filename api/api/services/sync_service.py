"""Endpoint-facing operations for change detection."""

from __future__ import annotations

import random
import uuid

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import SessionLocal
from api.ingest.normalize import pokemon_row
from api.ingest.sources import FixtureSource
from api.models import DataChange, Job, JobStatus, Move, Pokemon, SyncRun
from api.schemas import (
    ChangeRead,
    DriftEntry,
    DriftResponse,
    SimulateChangeRequest,
    SimulateChangeResponse,
    SimulatedMutation,
    SimulatedPokemon,
    SyncRunRead,
)
from api.sync import simulate
from api.sync.alerts import alert_text
from api.sync.hashing import section_hashes
from api.sync.normalize import HASHED_SECTIONS, normalize_pokemon
from api.sync.run import run_sync
from api.sync.simulate import MutationField

# Move ids offered as additions when simulating a movepool change.
ADDABLE_MOVE_SAMPLE = 200


async def list_sync_runs(session: AsyncSession, limit: int = 50) -> list[SyncRunRead]:
    """Run history, newest first."""
    rows = list(
        await session.scalars(select(SyncRun).order_by(desc(SyncRun.started_at)).limit(limit))
    )
    return [
        SyncRunRead(
            id=row.id,
            source=row.source.value,
            status=row.status,
            records_scanned=row.records_scanned,
            changes_found=row.changes_found,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_ms=(
                round((row.finished_at - row.started_at).total_seconds() * 1000, 2)
                if row.finished_at
                else None
            ),
        )
        for row in rows
    ]


async def list_changes(session: AsyncSession, limit: int = 50) -> list[ChangeRead]:
    """Recent detected changes, rendered as sentences."""
    rows = (
        await session.execute(
            select(DataChange, Pokemon.name)
            .outerjoin(
                Pokemon,
                (DataChange.entity_type == "pokemon")
                & (Pokemon.id == DataChange.entity_id.cast(Pokemon.id.type)),
            )
            .order_by(desc(DataChange.detected_at), desc(DataChange.id))
            .limit(limit)
        )
    ).all()

    # Move names are resolved in one query rather than per row.
    move_ids = {
        int(change.field_path[6:-1])
        for change, _ in rows
        if change.field_path.startswith("moves[") and change.field_path[6:-1].isdigit()
    }
    move_names: dict[int, str] = {}
    if move_ids:
        move_names = {
            row.id: row.name
            for row in (
                await session.execute(select(Move.id, Move.name).where(Move.id.in_(move_ids)))
            ).all()
        }

    result: list[ChangeRead] = []
    for change, pokemon_name in rows:
        move_name = None
        if change.field_path.startswith("moves["):
            digits = change.field_path[6:-1]
            if digits.isdigit():
                move_name = move_names.get(int(digits))
        result.append(
            ChangeRead(
                id=change.id,
                sync_run_id=change.sync_run_id,
                entity_type=change.entity_type,
                entity_id=change.entity_id,
                pokemon_name=pokemon_name,
                field_path=change.field_path,
                old_value=change.old_value,
                new_value=change.new_value,
                message=alert_text(
                    pokemon_name or change.entity_id,
                    change.field_path,
                    change.old_value,
                    change.new_value,
                    move_name=move_name,
                ),
                detected_at=change.detected_at,
            )
        )
    return result


async def drift(session: AsyncSession) -> DriftResponse:
    """Rows whose stored payload no longer matches the reference snapshot.

    Compared against the committed fixture rather than a live fetch, so this
    stays a fast read. It answers "what would a sync find right now" without
    issuing a few thousand HTTP requests to find out.
    """
    reference = {
        payload["id"]: section_hashes(normalize_pokemon(payload))
        for payload in (await FixtureSource().fetch_pokemon()).items
    }

    rows = (
        await session.execute(
            select(
                Pokemon.id,
                Pokemon.name,
                Pokemon.stats_hash,
                Pokemon.types_hash,
                Pokemon.moves_hash,
                Pokemon.sprite_hash,
            ).order_by(Pokemon.id)
        )
    ).all()

    entries: list[DriftEntry] = []
    for row in rows:
        expected = reference.get(row.id)
        if expected is None:
            continue
        stored = {
            "stats_hash": row.stats_hash,
            "types_hash": row.types_hash,
            "moves_hash": row.moves_hash,
            "sprite_hash": row.sprite_hash,
        }
        differing = [
            section
            for section in HASHED_SECTIONS
            if stored[f"{section}_hash"] != expected[f"{section}_hash"]
        ]
        if differing:
            entries.append(DriftEntry(pokemon_id=row.id, name=row.name, sections=differing))

    return DriftResponse(
        reference="fixture", checked=len(rows), drifted=len(entries), entries=entries
    )


async def simulate_change(
    session: AsyncSession, request: SimulateChangeRequest, rng: random.Random | None = None
) -> SimulateChangeResponse:
    """Introduce known divergences into our snapshot."""
    rng = rng or random.Random()

    groups = [MutationField(f) for f in request.fields] if request.fields else None

    if request.pokemon_ids:
        ids = list(dict.fromkeys(request.pokemon_ids))
    else:
        all_ids = list((await session.scalars(select(Pokemon.id))).all())
        ids = rng.sample(all_ids, k=min(request.count, len(all_ids)))

    rows = (
        await session.execute(
            select(Pokemon.id, Pokemon.name, Pokemon.raw).where(Pokemon.id.in_(ids))
        )
    ).all()
    found = {row.id: row for row in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f"Unknown Pokemon ids: {missing}.")

    addable = [
        (row.id, row.name)
        for row in (
            await session.execute(
                select(Move.id, Move.name).order_by(Move.id).limit(ADDABLE_MOVE_SAMPLE)
            )
        ).all()
    ]

    by_pokemon: list[SimulatedPokemon] = []
    total = 0

    for pokemon_id in ids:
        row = found[pokemon_id]
        # One random group per Pokemon when none were named, so repeated calls
        # exercise different sections.
        chosen_groups = groups or [rng.choice(list(MutationField))]

        mutated_raw, mutations = simulate.mutate_payload(
            row.raw, row.name, chosen_groups, request.mutations_per_field, rng, addable
        )
        if not mutations:
            continue

        # The entire row is rebuilt from the mutated payload rather than
        # patching individual columns. That is what guarantees every affected
        # section hash moves: mutate stats and types together and both
        # stats_hash and types_hash are recomputed, because none of them is
        # updated by hand.
        await session.execute(
            update(Pokemon).where(Pokemon.id == pokemon_id).values(**pokemon_row(mutated_raw))
        )

        total += len(mutations)
        by_pokemon.append(
            SimulatedPokemon(
                pokemon_id=pokemon_id,
                name=row.name,
                sections_touched=sorted({m.section for m in mutations}),
                mutations=[
                    SimulatedMutation(
                        field_path=m.field_path,
                        section=m.section,
                        upstream_value=m.upstream_value,
                        mutated_to=m.mutated_to,
                        expect_alert=m.expect_alert,
                    )
                    for m in mutations
                ],
            )
        )

    await session.commit()

    return SimulateChangeResponse(
        total_mutations=total,
        affected_pokemon=len(by_pokemon),
        mutations_per_field_effective=simulate.effective_allowances(
            groups or list(MutationField), request.mutations_per_field
        ),
        by_pokemon=by_pokemon,
    )


async def run_sync_job(job_id: uuid.UUID, source_name: str) -> None:
    """Background entry point for POST /admin/sync."""
    async with SessionLocal() as session:
        await session.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.running, detail="starting")
        )
        await session.commit()

    async def progress(message: str) -> None:
        async with SessionLocal() as session:
            await session.execute(update(Job).where(Job.id == job_id).values(detail=message))
            await session.commit()

    try:
        outcome = await run_sync(source_name, on_progress=progress)
    except Exception as exc:
        async with SessionLocal() as session:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status=JobStatus.failed, detail="failed", error=repr(exc))
            )
            await session.commit()
        return

    async with SessionLocal() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=JobStatus.succeeded if outcome.ok else JobStatus.failed,
                detail="done" if outcome.ok else outcome.status,
                result={
                    "sync_run_id": outcome.sync_run_id,
                    "records_scanned": outcome.records_scanned,
                    "changes_found": outcome.changes_found,
                    "source": outcome.source,
                },
                error=outcome.error,
            )
        )
        await session.commit()
