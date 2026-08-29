"""Tests for alert rendering.

One function serves two callers that must agree exactly: the simulator predicts
the alert a divergence will produce, and the changes feed renders it once
detected. A demo compares the two strings verbatim, so any divergence between
them is a visible failure.
"""

from __future__ import annotations

import pytest

from api.sync.alerts import alert_text, display_name


class TestDisplayName:
    @pytest.mark.parametrize(
        ("stored", "shown"),
        [("pikachu", "Pikachu"), ("mr-mime", "Mr-Mime"), ("ho-oh", "Ho-Oh")],
    )
    def test_capitalises_each_part(self, stored: str, shown: str) -> None:
        assert display_name(stored) == shown


class TestStats:
    def test_matches_the_documented_example(self) -> None:
        assert alert_text("pikachu", "stats.attack", 71, 55) == (
            "Pikachu's Attack changed from 71 to 55"
        )

    @pytest.mark.parametrize(
        ("stat", "label"),
        [
            ("hp", "HP"),
            ("attack", "Attack"),
            ("special-attack", "Special Attack"),
            ("special-defense", "Special Defense"),
            ("speed", "Speed"),
        ],
    )
    def test_uses_player_facing_labels(self, stat: str, label: str) -> None:
        """`special-attack` is an API spelling, not something a player says."""
        assert f"'s {label} changed" in alert_text("pikachu", f"stats.{stat}", 1, 2)


class TestTypes:
    def test_matches_the_documented_example(self) -> None:
        assert alert_text("pikachu", "types[0]", "ghost", "electric") == (
            "Pikachu's primary type changed from ghost to electric"
        )

    def test_secondary_slot_is_named(self) -> None:
        assert "secondary type" in alert_text("charizard", "types[1]", "fairy", "flying")

    def test_a_gained_type_reads_as_gained(self) -> None:
        assert alert_text("pikachu", "types[1]", None, "psychic") == (
            "Pikachu gained a secondary type of psychic"
        )

    def test_a_lost_type_reads_as_lost(self) -> None:
        assert alert_text("pikachu", "types[1]", "psychic", None) == (
            "Pikachu lost its secondary type of psychic"
        )


class TestSprite:
    def test_does_not_print_the_urls(self) -> None:
        """Two near-identical URLs in a sentence tell a reader nothing."""
        message = alert_text("pikachu", "sprite", "https://a/25.png", "https://a/25.png?v=2")
        assert message == "Pikachu's sprite changed"
        assert "http" not in message


class TestMoves:
    def test_a_move_appearing_reads_as_learned(self) -> None:
        assert alert_text("pikachu", "moves[85]", None, "85", move_name="thunderbolt") == (
            "Pikachu learned Thunderbolt"
        )

    def test_a_move_disappearing_reads_as_forgotten(self) -> None:
        assert alert_text("pikachu", "moves[85]", "85", None, move_name="thunderbolt") == (
            "Pikachu forgot Thunderbolt"
        )

    def test_falls_back_to_the_id_when_the_name_is_unknown(self) -> None:
        assert "move #85" in alert_text("pikachu", "moves[85]", None, "85")


class TestAbilities:
    def test_gained(self) -> None:
        assert alert_text("pikachu", "abilities.static", None, "False") == (
            "Pikachu gained the ability Static"
        )

    def test_lost(self) -> None:
        assert "lost the ability" in alert_text("pikachu", "abilities.static", "False", None)


class TestUnknownPaths:
    def test_still_renders_something_useful(self) -> None:
        """An unrecognised path must not crash the feed."""
        assert alert_text("pikachu", "height", "4", "5") == ("Pikachu's height changed from 4 to 5")
