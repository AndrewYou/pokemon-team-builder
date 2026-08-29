"""Capture a live PokeAPI snapshot to disk.

Run with `python -m api.ingest.fixture`. This is the only code path that is
expected to hit pokeapi.co in bulk, and it exists so that everything else --
tests, CI, a fresh clone -- can work offline against a committed snapshot.

Payloads are trimmed before they are written. A faithful copy would be roughly
400 MB, over 90% of which is per-move, per-game learn data we never read.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api.config import settings
from api.ingest import normalize
from api.ingest.client import RateLimitedClient
from api.ingest.sources import DEFAULT_FIXTURE_PATH, LiveSource


async def build_snapshot(source: LiveSource) -> tuple[dict[str, Any], list[str]]:
    """Fetch everything and return the snapshot plus any failure descriptions."""
    types = await source.fetch_types()
    moves = await source.fetch_moves()
    pokemon = await source.fetch_pokemon()

    failures = [
        f"{failure.url} -> {failure.error}"
        for failure in (*types.failures, *moves.failures, *pokemon.failures)
    ]

    snapshot: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "https://pokeapi.co/api/v2",
        "note": (
            "Payloads are trimmed to the fields this project stores. "
            "See api/ingest/normalize.py for exactly what is dropped."
        ),
        "counts": {
            "pokemon": len(pokemon.items),
            "moves": len(moves.items),
            "types": len(types.items),
        },
        "types": [normalize.trim_type(p) for p in sorted(types.items, key=lambda p: p["id"])],
        "moves": [normalize.trim_move(p) for p in sorted(moves.items, key=lambda p: p["id"])],
        "pokemon": [
            normalize.trim_pokemon(p) for p in sorted(pokemon.items, key=lambda p: p["id"])
        ],
    }
    return snapshot, failures


def write_snapshot(snapshot: dict[str, Any], path: Path = DEFAULT_FIXTURE_PATH) -> int:
    """Write the snapshot compactly and return its size in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Compact separators: the indentation on a 20 MB document is pure cost.
    text = json.dumps(snapshot, separators=(",", ":"), sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


async def _run() -> int:
    async with RateLimitedClient(
        settings.pokeapi_base_url,
        concurrency=settings.pokeapi_concurrency,
        batch_delay=settings.pokeapi_batch_delay,
    ) as client:
        snapshot, failures = await build_snapshot(LiveSource(client))

    if failures:
        # Refuse to write a partial snapshot. A fixture that is quietly missing
        # 40 Pokemon is worse than no fixture: it gets committed and believed.
        print(
            f"\n{len(failures)} fetch failure(s); refusing to write a partial fixture:",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    size = write_snapshot(snapshot)
    counts = snapshot["counts"]
    print(
        f"\nWrote {DEFAULT_FIXTURE_PATH.relative_to(DEFAULT_FIXTURE_PATH.parents[1])}: "
        f"{size / 1024 / 1024:.1f} MB "
        f"({counts['pokemon']} pokemon, {counts['moves']} moves, {counts['types']} types)"
    )
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
