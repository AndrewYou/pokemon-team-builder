"""Tests for the derived-cache singleton."""

import pytest

from api.derived import registry


@pytest.fixture(autouse=True)
def _clean() -> None:
    registry.invalidate()


def test_unbuilt_cache_raises_with_instructions() -> None:
    """The error names the two calls that fix it, since the reviewer only has
    a browser."""
    with pytest.raises(registry.DerivedCacheUnavailable, match="cache/rebuild"):
        registry.get_cache()


def test_peek_returns_none_without_raising() -> None:
    assert registry.peek() is None


def test_invalidate_is_idempotent() -> None:
    registry.invalidate()
    registry.invalidate()
    assert registry.peek() is None
