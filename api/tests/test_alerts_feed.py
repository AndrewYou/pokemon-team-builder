"""Tests for the alert feed's grouping and path parsing.

The join behind /alerts multiplies rows: one change to a Pokemon on three of
your teams comes back three times. Collapsing that correctly is the part worth
testing, and it is pure once the rows are in hand.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pytest

from api.services.alerts import WINDOW_DAYS, group_alert_rows, move_id_from_path

NOW = datetime.datetime(2026, 8, 29, 14, 0, tzinfo=datetime.UTC)


@dataclass(frozen=True)
class Row:
    """One joined row, shaped like what the query returns."""

    id: int
    field_path: str
    old_value: str | None
    new_value: str | None
    detected_at: datetime.datetime
    pokemon_id: int
    pokemon_name: str
    sprite_url: str | None
    team_id: int
    team_name: str


def _row(
    change_id: int, pokemon: tuple[int, str], team: tuple[int, str], path: str = "stats.attack"
) -> Row:
    return Row(
        id=change_id,
        field_path=path,
        old_value="55",
        new_value="60",
        detected_at=NOW,
        pokemon_id=pokemon[0],
        pokemon_name=pokemon[1],
        sprite_url=f"https://img/{pokemon[0]}.png",
        team_id=team[0],
        team_name=team[1],
    )


PIKACHU = (25, "pikachu")
CHARIZARD = (6, "charizard")
TEAM_A = (1, "Kanto classics")
TEAM_B = (2, "Speed run")
TEAM_C = (3, "Third")


class TestGrouping:
    def test_one_change_on_one_team(self) -> None:
        groups = group_alert_rows([_row(41, PIKACHU, TEAM_A)], {})
        assert len(groups) == 1
        assert groups[0].pokemon_name == "pikachu"
        assert len(groups[0].changes) == 1

    def test_the_same_change_across_three_teams_is_reported_once(self) -> None:
        """The join returns three rows. Showing the alert three times would be
        the obvious bug."""
        rows = [_row(41, PIKACHU, team) for team in (TEAM_A, TEAM_B, TEAM_C)]
        groups = group_alert_rows(rows, {})
        assert len(groups) == 1
        assert len(groups[0].changes) == 1

    def test_all_affected_teams_are_listed(self) -> None:
        rows = [_row(41, PIKACHU, team) for team in (TEAM_A, TEAM_B, TEAM_C)]
        (group,) = group_alert_rows(rows, {})
        assert [t.team_name for t in group.affected_teams] == [
            "Kanto classics",
            "Speed run",
            "Third",
        ]

    def test_teams_are_not_duplicated(self) -> None:
        """Two changes on a Pokemon in one team yields two rows for that team."""
        rows = [_row(41, PIKACHU, TEAM_A), _row(42, PIKACHU, TEAM_A)]
        (group,) = group_alert_rows(rows, {})
        assert len(group.affected_teams) == 1
        assert len(group.changes) == 2

    def test_several_pokemon_produce_several_groups(self) -> None:
        rows = [_row(41, PIKACHU, TEAM_A), _row(42, CHARIZARD, TEAM_A)]
        groups = group_alert_rows(rows, {})
        assert {g.pokemon_name for g in groups} == {"pikachu", "charizard"}

    def test_row_order_is_preserved(self) -> None:
        """The query orders newest first; grouping must not reshuffle that."""
        rows = [_row(43, CHARIZARD, TEAM_A), _row(41, PIKACHU, TEAM_A)]
        assert [g.pokemon_id for g in group_alert_rows(rows, {})] == [6, 25]

    def test_empty_input(self) -> None:
        assert group_alert_rows([], {}) == []


class TestMessages:
    def test_changes_read_as_sentences_not_diffs(self) -> None:
        (group,) = group_alert_rows([_row(41, PIKACHU, TEAM_A)], {})
        assert group.changes[0].message == "Pikachu's Attack changed from 55 to 60"

    def test_move_names_are_resolved_when_known(self) -> None:
        rows = [_row(41, PIKACHU, TEAM_A, path="moves[85]")]
        (group,) = group_alert_rows(rows, {85: "thunderbolt"})
        assert "Thunderbolt" in group.changes[0].message

    def test_move_falls_back_to_the_id(self) -> None:
        rows = [_row(41, PIKACHU, TEAM_A, path="moves[85]")]
        (group,) = group_alert_rows(rows, {})
        assert "move #85" in group.changes[0].message

    def test_the_change_id_is_exposed_for_dismissal(self) -> None:
        (group,) = group_alert_rows([_row(41, PIKACHU, TEAM_A)], {})
        assert group.changes[0].change_id == 41


class TestMoveIdFromPath:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("moves[85]", 85),
            ("moves[1]", 1),
            ("stats.attack", None),
            ("types[0]", None),
            ("sprite", None),
            ("moves[]", None),
            ("moves[abc]", None),
        ],
    )
    def test_parses_only_move_paths(self, path: str, expected: int | None) -> None:
        """A types[0] path must not be read as move id 0, which would send a
        wrong name into an alert."""
        assert move_id_from_path(path) == expected


class TestWindow:
    def test_is_seven_days(self) -> None:
        assert WINDOW_DAYS == 7
