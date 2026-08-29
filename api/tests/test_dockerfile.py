"""Tests for the deployed image's contents.

These assert facts about the Dockerfile itself rather than about the code,
because the failures they catch are invisible locally: everything works from a
checkout and breaks only in the container. Two have already happened -- a
BuildKit cache mount the platform rejected, and the fixture directory never
being copied, which made `source=fixture` a 500 in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.ingest.sources import DEFAULT_FIXTURE_PATH

API_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (API_ROOT / "Dockerfile").read_text()
DOCKERIGNORE = (API_ROOT / ".dockerignore").read_text()

# Comments are stripped before asserting on instructions. The Dockerfile
# documents why the BuildKit cache mount is absent, and a naive substring search
# over the whole file matches that explanation instead of a real directive.
INSTRUCTIONS = "\n".join(
    line for line in DOCKERFILE.splitlines() if line.strip() and not line.lstrip().startswith("#")
)

COPY_SOURCES = [
    source
    for line in DOCKERFILE.splitlines()
    if line.startswith("COPY") and "--from" not in line
    for source in line.split()[1:-1]
]


class TestRuntimeFilesAreInTheImage:
    """Anything read at runtime has to be copied, or it is a 500 in production
    and perfectly fine on a laptop."""

    @pytest.mark.parametrize("path", ["fixtures", "api", "alembic", "alembic.ini"])
    def test_copied(self, path: str) -> None:
        assert path in COPY_SOURCES, f"Dockerfile never copies {path!r}"

    def test_fixture_exists_in_the_repository(self) -> None:
        """A COPY of an empty directory would satisfy the test above."""
        assert DEFAULT_FIXTURE_PATH.exists()
        assert DEFAULT_FIXTURE_PATH.stat().st_size > 1_000_000

    def test_fixture_lives_under_a_copied_directory(self) -> None:
        """The path the code resolves must be inside what the image receives."""
        assert DEFAULT_FIXTURE_PATH.relative_to(API_ROOT).parts[0] in COPY_SOURCES

    @pytest.mark.parametrize("pattern", ["fixtures", "alembic", "api"])
    def test_not_excluded_by_dockerignore(self, pattern: str) -> None:
        ignored = {line.strip() for line in DOCKERIGNORE.splitlines() if line.strip()}
        assert pattern not in ignored


class TestStartCommand:
    """Each of these has already broken a deploy once."""

    def test_binds_all_interfaces(self) -> None:
        """127.0.0.1 yields a container that starts fine and is unreachable."""
        assert "--host 0.0.0.0" in INSTRUCTIONS

    def test_uses_the_injected_port(self) -> None:
        assert "${PORT:-8000}" in INSTRUCTIONS

    def test_migrates_before_serving(self) -> None:
        """Otherwise a deploy that adds a table answers 500s against an old
        schema, which is exactly how the job table failed."""
        cmd = INSTRUCTIONS[INSTRUCTIONS.index("CMD ") :]
        assert "alembic upgrade head" in cmd
        assert cmd.index("alembic upgrade head") < cmd.index("uvicorn")

    def test_migration_failure_stops_the_container(self) -> None:
        """`&&`, not `;`: never serve a half-migrated database."""
        assert re.search(r"alembic upgrade head\s*&&", INSTRUCTIONS)

    def test_runs_a_single_worker(self) -> None:
        """The derived cache is per-process, so invalidation would not
        propagate across workers. See the README."""
        assert "--workers" not in INSTRUCTIONS

    def test_no_buildkit_cache_mount(self) -> None:
        """Railway requires cache mount ids to be prefixed with the service id,
        which would pin the image to one service."""
        assert "--mount=type=cache" not in INSTRUCTIONS


class TestImageHygiene:
    def test_runs_as_a_non_root_user(self) -> None:
        assert "USER appuser" in INSTRUCTIONS

    def test_pins_the_python_minor_version(self) -> None:
        """greenlet lags new interpreter releases, and an unpinned build once
        resolved to a version with no wheel for it."""
        assert "python:3.12-slim" in INSTRUCTIONS
        assert ".python-version" in COPY_SOURCES
