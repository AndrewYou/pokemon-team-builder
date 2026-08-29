"""Debug surface for normalisation and hashing."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Pokemon
from api.schemas import (
    DeterminismCheckResponse,
    DeterminismMismatch,
    NormalizeDebugResponse,
)
from api.sync.hashing import section_hashes
from api.sync.normalize import dropped_fields, normalize_pokemon

MAX_SAMPLES = 10


async def normalize_debug(session: AsyncSession, pokemon_id: int) -> NormalizeDebugResponse | None:
    """Show a stored payload beside its projection."""
    row = (
        await session.execute(
            select(
                Pokemon.id,
                Pokemon.name,
                Pokemon.raw,
                Pokemon.stats_hash,
                Pokemon.types_hash,
                Pokemon.moves_hash,
                Pokemon.sprite_hash,
            ).where(Pokemon.id == pokemon_id)
        )
    ).first()
    if row is None:
        return None

    normalized = normalize_pokemon(row.raw)
    fresh = section_hashes(normalized)
    stored = {
        "stats_hash": row.stats_hash,
        "types_hash": row.types_hash,
        "moves_hash": row.moves_hash,
        "sprite_hash": row.sprite_hash,
    }

    return NormalizeDebugResponse(
        pokemon_id=row.id,
        pokemon_name=row.name,
        raw_field_count=len(row.raw),
        normalized_field_count=len(normalized),
        dropped_fields=dropped_fields(row.raw),
        normalized=normalized,
        section_hashes=fresh,
        stored_hashes=stored,
        hashes_match=fresh == stored,
    )


async def determinism_check(session: AsyncSession) -> DeterminismCheckResponse:
    """Re-normalise and re-hash every stored Pokemon, comparing to the database.

    A mismatch means normalisation is not a pure function of the stored payload,
    which would make the next sync report every Pokemon as changed. That turns
    the change feed into noise, so this is checked directly rather than assumed.
    """
    started = time.perf_counter()
    rows = (
        await session.execute(
            select(
                Pokemon.id,
                Pokemon.name,
                Pokemon.raw,
                Pokemon.stats_hash,
                Pokemon.types_hash,
                Pokemon.moves_hash,
                Pokemon.sprite_hash,
            ).order_by(Pokemon.id)
        )
    ).all()

    samples: list[DeterminismMismatch] = []
    mismatches = 0
    sections = 0

    for row in rows:
        fresh = section_hashes(normalize_pokemon(row.raw))
        stored = {
            "stats_hash": row.stats_hash,
            "types_hash": row.types_hash,
            "moves_hash": row.moves_hash,
            "sprite_hash": row.sprite_hash,
        }
        for section, stored_hash in stored.items():
            sections += 1
            if fresh[section] == stored_hash:
                continue
            mismatches += 1
            if len(samples) < MAX_SAMPLES:
                samples.append(
                    DeterminismMismatch(
                        pokemon_id=row.id,
                        pokemon_name=row.name,
                        section=section,
                        stored_hash=stored_hash,
                        recomputed_hash=fresh[section],
                    )
                )

    return DeterminismCheckResponse(
        checked=len(rows),
        sections_checked=sections,
        mismatches=mismatches,
        mismatch_samples=samples,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        ok=mismatches == 0,
    )
