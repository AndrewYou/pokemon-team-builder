"""Tests for catalog pagination internals.

Cursor encoding is pure and is the part that silently corrupts an infinite
scroll if it goes wrong: a bad cursor does not error, it skips or repeats rows.
"""

from __future__ import annotations

import pytest

from api.services.catalog import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    CursorError,
    decode_cursor,
    encode_cursor,
)


class TestCursorRoundTrip:
    @pytest.mark.parametrize(
        ("key", "pokemon_id"),
        [(6, 6), ("charizard", 6), (1025, 1025), ("nidoran-f", 29), ("", 1)],
    )
    def test_round_trips(self, key: str | int, pokemon_id: int) -> None:
        assert decode_cursor(encode_cursor(key, pokemon_id)) == (key, pokemon_id)

    def test_is_url_safe(self) -> None:
        """Cursors travel in a query string, so + and / would need escaping."""
        cursor = encode_cursor("a" * 40, 999)
        assert "+" not in cursor
        assert "/" not in cursor
        assert "=" not in cursor

    def test_is_opaque(self) -> None:
        """Clients must not be tempted to construct one by hand."""
        assert "charizard" not in encode_cursor("charizard", 6)

    def test_distinct_positions_give_distinct_cursors(self) -> None:
        assert encode_cursor("a", 1) != encode_cursor("a", 2)


class TestCursorValidation:
    @pytest.mark.parametrize("cursor", ["not-base64!!", "", "eyJib2d1cyI6MX0", "AAAA", "%%%%"])
    def test_malformed_cursors_raise(self, cursor: str) -> None:
        """Rejected explicitly so the router can answer 400 rather than
        crashing or, worse, silently starting from the beginning again."""
        with pytest.raises(CursorError):
            decode_cursor(cursor)

    def test_missing_padding_is_tolerated(self) -> None:
        """Padding is stripped on the way out, so it must be restored on the
        way in."""
        cursor = encode_cursor("charizard", 6)
        assert decode_cursor(cursor) == ("charizard", 6)


class TestLimits:
    def test_default_page_size(self) -> None:
        assert DEFAULT_LIMIT == 48

    def test_maximum_page_size(self) -> None:
        assert MAX_LIMIT == 100
