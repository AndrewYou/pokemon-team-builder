"""Where seed data comes from.

The Protocol is the seam that makes the rest of this tractable: the seed script
never knows whether it is talking to pokeapi.co or to a JSON file on disk. That
matters for tests, which must never touch the network, and for the change
detection demo, which needs to replay a known-good snapshot against a modified
one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from api.config import settings
from api.ingest.client import FetchFailure, RateLimitedClient

# api/api/ingest/sources.py -> api/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "pokeapi-snapshot.json"


@dataclass(slots=True)
class FetchResult:
    """Successfully fetched payloads, plus everything that failed.

    Failures travel alongside the data rather than being raised immediately, so
    a single bad resource does not throw away a run that took minutes. The
    caller is responsible for turning a non-empty `failures` into a non-zero
    exit code -- see seed.py.
    """

    items: list[dict[str, Any]] = field(default_factory=list)
    failures: list[FetchFailure] = field(default_factory=list)


class PokemonSource(Protocol):
    """A provider of raw PokeAPI-shaped payloads."""

    name: str

    async def fetch_pokemon(self) -> FetchResult: ...

    async def fetch_moves(self) -> FetchResult: ...

    async def fetch_types(self) -> FetchResult: ...


class LiveSource:
    """Fetches from pokeapi.co, rate limited."""

    name = "live"

    def __init__(self, client: RateLimitedClient) -> None:
        self._client = client

    async def _index(self, resource: str) -> list[str]:
        """Return every detail URL for a resource type."""
        index = await self._client.get_json(f"{resource}?limit=100000")
        return [entry["url"] for entry in index["results"]]

    async def fetch_pokemon(self) -> FetchResult:
        urls = await self._index("pokemon")
        items, failures = await self._client.get_many(urls, desc="pokemon")
        # is_default is only visible on the detail payload, so alternate forms
        # are filtered after the fetch rather than before it.
        return FetchResult(items=[p for p in items if p.get("is_default")], failures=failures)

    async def fetch_moves(self) -> FetchResult:
        urls = await self._index("move")
        items, failures = await self._client.get_many(urls, desc="moves")
        return FetchResult(items=items, failures=failures)

    async def fetch_types(self) -> FetchResult:
        urls = await self._index("type")
        items, failures = await self._client.get_many(urls, desc="types")
        return FetchResult(items=items, failures=failures)


class FixtureSource:
    """Reads a previously captured snapshot from disk.

    This is the default so that nobody hammers PokeAPI by accident, and so the
    repository is self-contained: clone, seed, run.
    """

    name = "fixture"

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (
            Path(settings.pokeapi_fixture_path)
            if settings.pokeapi_fixture_path
            else DEFAULT_FIXTURE_PATH
        )
        self._snapshot: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._snapshot is None:
            if not self._path.exists():
                raise FileNotFoundError(
                    f"No fixture at {self._path}. Generate one with "
                    f"`python -m api.ingest.fixture` (this hits the live API)."
                )
            with self._path.open(encoding="utf-8") as handle:
                self._snapshot = json.load(handle)
        return self._snapshot

    async def fetch_pokemon(self) -> FetchResult:
        return FetchResult(items=self._load()["pokemon"])

    async def fetch_moves(self) -> FetchResult:
        return FetchResult(items=self._load()["moves"])

    async def fetch_types(self) -> FetchResult:
        return FetchResult(items=self._load()["types"])


def build_source(name: str | None = None, client: RateLimitedClient | None = None) -> PokemonSource:
    """Select a source by name, defaulting to the POKEAPI_SOURCE env var.

    Unknown names are rejected rather than silently falling back: quietly
    reading a stale fixture when a live sync was intended is exactly the kind of
    failure this task is meant to make impossible.
    """
    chosen = (name or settings.pokeapi_source).strip().lower()
    if chosen == "fixture":
        return FixtureSource()
    if chosen == "live":
        if client is None:
            raise ValueError("LiveSource requires a RateLimitedClient")
        return LiveSource(client)
    raise ValueError(f"Unknown source {chosen!r}; expected 'fixture' or 'live'")
