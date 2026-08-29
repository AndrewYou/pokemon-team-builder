"""Tests for the rate-limited client and the source Protocol.

Everything here runs against an in-process transport. No test in this suite may
touch pokeapi.co -- that is both a courtesy and the reason CI is deterministic.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.ingest.client import RateLimitedClient
from api.ingest.sources import FixtureSource, LiveSource, build_source


class ScriptedTransport(httpx.AsyncBaseTransport):
    """Replays a scripted list of status codes and tracks concurrency."""

    def __init__(self, statuses: list[int] | None = None, payload: Any = None) -> None:
        self.statuses = statuses or []
        self.payload = payload if payload is not None else {"ok": True}
        self.request_count = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            # Yield control so overlapping requests can actually overlap.
            await asyncio.sleep(0.01)
            status = self.statuses.pop(0) if self.statuses else 200
            body = json.dumps(self.payload if status == 200 else {"error": status})
            return httpx.Response(
                status, content=body, headers={"content-type": "application/json"}
            )
        finally:
            self.in_flight -= 1


async def test_retries_on_429_then_succeeds() -> None:
    transport = ScriptedTransport(statuses=[429, 200], payload={"id": 1})
    async with RateLimitedClient("http://test", transport=transport, max_attempts=3) as client:
        assert await client.get_json("pokemon/1") == {"id": 1}
    assert transport.request_count == 2


async def test_retries_on_500() -> None:
    transport = ScriptedTransport(statuses=[500, 200], payload={"id": 2})
    async with RateLimitedClient("http://test", transport=transport, max_attempts=3) as client:
        assert await client.get_json("pokemon/2") == {"id": 2}
    assert transport.request_count == 2


async def test_does_not_retry_404() -> None:
    """A 404 is a real answer about a real resource; retrying only wastes time."""
    transport = ScriptedTransport(statuses=[404])
    async with RateLimitedClient("http://test", transport=transport, max_attempts=4) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_json("pokemon/999999")
    assert transport.request_count == 1


async def test_gives_up_after_max_attempts() -> None:
    transport = ScriptedTransport(statuses=[503, 503])
    async with RateLimitedClient("http://test", transport=transport, max_attempts=2) as client:
        with pytest.raises(Exception, match="503"):
            await client.get_json("pokemon/1")
    assert transport.request_count == 2


async def test_concurrency_never_exceeds_the_semaphore() -> None:
    """The politeness guarantee. If this regresses, we start hammering PokeAPI."""
    transport = ScriptedTransport()
    async with RateLimitedClient(
        "http://test", transport=transport, concurrency=3, batch_size=50, batch_delay=0
    ) as client:
        items, failures = await client.get_many([f"pokemon/{i}" for i in range(30)], desc="t")
    assert len(items) == 30
    assert not failures
    assert transport.max_in_flight <= 3


async def test_get_many_collects_failures_without_raising() -> None:
    """One bad resource must not discard a run that took minutes."""
    transport = ScriptedTransport(statuses=[404, 200, 200])
    async with RateLimitedClient(
        "http://test", transport=transport, batch_delay=0, max_attempts=1
    ) as client:
        items, failures = await client.get_many(["a", "b", "c"], desc="t")
    assert len(items) == 2
    assert len(failures) == 1
    assert "404" in failures[0].error


async def test_live_source_filters_non_default_forms() -> None:
    """Alternate forms share an index with default ones and must be dropped."""

    class IndexTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if "limit" in str(request.url):
                body: Any = {
                    "results": [
                        {"url": "http://test/pokemon/1"},
                        {"url": "http://test/pokemon/2"},
                    ]
                }
            elif str(request.url).endswith("/1"):
                body = {"id": 1, "name": "a", "is_default": True}
            else:
                body = {"id": 2, "name": "a-mega", "is_default": False}
            return httpx.Response(200, json=body)

    async with RateLimitedClient("http://test", transport=IndexTransport(), batch_delay=0) as c:
        result = await LiveSource(c).fetch_pokemon()
    assert [p["name"] for p in result.items] == ["a"]


class TestFixtureSource:
    def _write(self, tmp_path: Path) -> Path:
        path = tmp_path / "snap.json"
        path.write_text(json.dumps({"pokemon": [{"id": 1}], "moves": [{"id": 33}], "types": []}))
        return path

    async def test_reads_each_section(self, tmp_path: Path) -> None:
        source = FixtureSource(self._write(tmp_path))
        assert (await source.fetch_pokemon()).items == [{"id": 1}]
        assert (await source.fetch_moves()).items == [{"id": 33}]

    async def test_reports_no_failures(self, tmp_path: Path) -> None:
        assert (await FixtureSource(self._write(tmp_path)).fetch_pokemon()).failures == []

    async def test_missing_fixture_explains_how_to_build_one(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="api.ingest.fixture"):
            await FixtureSource(tmp_path / "absent.json").fetch_pokemon()


class TestBuildSource:
    def test_defaults_to_fixture(self) -> None:
        assert build_source("fixture").name == "fixture"

    def test_live_requires_a_client(self) -> None:
        with pytest.raises(ValueError, match="requires a RateLimitedClient"):
            build_source("live")

    def test_unknown_source_is_rejected_not_defaulted(self) -> None:
        """Silently falling back to a stale fixture when a live sync was asked
        for is precisely the confusion this project exists to eliminate."""
        with pytest.raises(ValueError, match="Unknown source"):
            build_source("typo")
