"""Tests that reference-data writes refresh the derived layer.

Defensive vectors are precomputed, so a stale cache does not fail loudly -- it
answers confidently wrong. The vector endpoint reads types live from the
database but multipliers from the cached matrix, so a Pokemon whose typing
changed reports its new types alongside its old multipliers, in one
self-contradicting response.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from api.derived import registry
from api.ingest.seed import SeedReport
from api.services import jobs as job_service


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Neutralise the database and record what the job does to the registry."""
    calls: list[str] = []

    async def fake_set_job(_job_id: uuid.UUID, **_values: Any) -> None:
        return None

    async def fake_rebuild(_session: Any) -> None:
        calls.append("rebuild")

    def fake_invalidate() -> None:
        calls.append("invalidate")

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(job_service, "_set_job", fake_set_job)
    monkeypatch.setattr(job_service, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(registry, "rebuild", fake_rebuild)
    monkeypatch.setattr(registry, "invalidate", fake_invalidate)
    return calls


class TestSeedRefreshesTheCache:
    async def test_successful_seed_rebuilds(
        self, monkeypatch: pytest.MonkeyPatch, recorded: list[str]
    ) -> None:
        async def fake_seed(_source: Any, on_progress: Any = None) -> SeedReport:
            return SeedReport(counts={"pokemon": 1})

        monkeypatch.setattr(job_service, "seed", fake_seed)
        monkeypatch.setattr(job_service, "build_source", lambda *_: object())

        await job_service.run_seed_job(uuid.uuid4(), "fixture")
        assert "rebuild" in recorded

    async def test_seed_with_errors_still_rebuilds(
        self, monkeypatch: pytest.MonkeyPatch, recorded: list[str]
    ) -> None:
        """Rows were still written, so the cache still describes old data."""
        from api.ingest.seed import RecordError

        async def fake_seed(_source: Any, on_progress: Any = None) -> SeedReport:
            return SeedReport(
                counts={"pokemon": 1},
                record_errors=[RecordError("pokemon", "ivysaur", "KeyError")],
            )

        monkeypatch.setattr(job_service, "seed", fake_seed)
        monkeypatch.setattr(job_service, "build_source", lambda *_: object())

        await job_service.run_seed_job(uuid.uuid4(), "fixture")
        assert "rebuild" in recorded

    async def test_a_failed_rebuild_invalidates_instead_of_serving_stale(
        self, monkeypatch: pytest.MonkeyPatch, recorded: list[str]
    ) -> None:
        """Unbuilt answers 503 and says how to fix it. Stale is silently wrong,
        so it is never the fallback."""

        async def fake_seed(_source: Any, on_progress: Any = None) -> SeedReport:
            return SeedReport(counts={"pokemon": 1})

        async def exploding_rebuild(_session: Any) -> None:
            raise RuntimeError("database went away")

        monkeypatch.setattr(job_service, "seed", fake_seed)
        monkeypatch.setattr(job_service, "build_source", lambda *_: object())
        monkeypatch.setattr(registry, "rebuild", exploding_rebuild)

        await job_service.run_seed_job(uuid.uuid4(), "fixture")
        assert recorded == ["invalidate"]

    async def test_a_crashed_seed_does_not_rebuild(
        self, monkeypatch: pytest.MonkeyPatch, recorded: list[str]
    ) -> None:
        """Nothing was written, so the existing cache is still accurate."""

        async def exploding_seed(_source: Any, on_progress: Any = None) -> SeedReport:
            raise RuntimeError("fetch failed")

        monkeypatch.setattr(job_service, "seed", exploding_seed)
        monkeypatch.setattr(job_service, "build_source", lambda *_: object())

        await job_service.run_seed_job(uuid.uuid4(), "fixture")
        assert recorded == []
