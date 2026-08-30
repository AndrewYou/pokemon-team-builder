"""Tests for the movepool collapse.

The collapse claims to be lossless, not a heuristic. Within one
(type, damage class) group the attacker's stat, the defender's stat and the
effectiveness multiplier are identical, so damage rises strictly with power and
the strongest move in a group beats the rest against every defender. These
tests hold that claim to account.
"""

from __future__ import annotations

import itertools

import pytest

from api.derived.moves import BestMove, MoveRow, collapse


def move(
    id: int, name: str, type: str, damage_class: str, power: int | None, accuracy: int | None = 100
) -> MoveRow:
    return MoveRow(
        id=id, name=name, type=type, damage_class=damage_class, power=power, accuracy=accuracy
    )


class TestKeepsTheStrongest:
    def test_flamethrower_beats_ember(self) -> None:
        result = collapse(
            [
                move(52, "ember", "fire", "special", 40),
                move(53, "flamethrower", "fire", "special", 90),
            ]
        )
        assert [m.name for m in result] == ["flamethrower"]

    def test_groups_are_independent(self) -> None:
        """Same type, different class: both survive, because they draw on
        different stats and neither dominates the other."""
        result = collapse(
            [
                move(53, "flamethrower", "fire", "special", 90),
                move(7, "fire-punch", "fire", "physical", 75),
            ]
        )
        assert {m.damage_class for m in result} == {"special", "physical"}

    def test_different_types_are_independent(self) -> None:
        result = collapse(
            [
                move(53, "flamethrower", "fire", "special", 90),
                move(58, "ice-beam", "ice", "special", 90),
            ]
        )
        assert len(result) == 2

    def test_ties_resolve_on_id_not_input_order(self) -> None:
        forward = collapse(
            [move(10, "a", "fire", "special", 90), move(5, "b", "fire", "special", 90)]
        )
        backward = collapse(
            [move(5, "b", "fire", "special", 90), move(10, "a", "fire", "special", 90)]
        )
        assert forward[0].id == backward[0].id == 5


class TestDrops:
    def test_status_moves(self) -> None:
        """No power, no damage, no place in a damage model."""
        assert collapse([move(45, "growl", "normal", "status", None)]) == []

    def test_zero_power_damaging_moves(self) -> None:
        assert collapse([move(1, "odd", "normal", "physical", 0)]) == []

    @pytest.mark.parametrize("bad_type", ["shadow", "stellar", "unknown"])
    def test_non_canonical_types(self, bad_type: str) -> None:
        """These exist upstream, and a defensive-vector lookup on one raises a
        KeyError in the middle of a request."""
        assert collapse([move(1, "odd", bad_type, "physical", 100)]) == []

    def test_a_dropped_type_does_not_take_its_group_with_it(self) -> None:
        result = collapse(
            [
                move(1, "shadow-rush", "shadow", "physical", 200),
                move(2, "tackle", "normal", "physical", 40),
            ]
        )
        assert [m.name for m in result] == ["tackle"]


class TestLossless:
    """The property that matters: no discarded move could have beaten the one
    kept, against any defender."""

    def test_the_kept_move_wins_every_group_comparison(self) -> None:
        pool = [
            move(1, "ember", "fire", "special", 40),
            move(2, "flamethrower", "fire", "special", 90),
            move(3, "fire-blast", "fire", "special", 110),
            move(4, "fire-punch", "fire", "physical", 75),
            move(5, "flare-blitz", "fire", "physical", 120),
            move(6, "tackle", "normal", "physical", 40),
        ]
        kept = {(m.type, m.damage_class): m for m in collapse(pool)}
        for original in pool:
            if original.power is None or original.power == 0:
                continue
            winner = kept[(original.type, original.damage_class)]
            # Damage is strictly increasing in power once the group is fixed,
            # so keeping the highest power is the same as keeping the winner.
            assert winner.power >= original.power

    def test_every_group_present_in_the_input_survives(self) -> None:
        pool = [
            move(i, f"m{i}", type_name, damage_class, 50 + i)
            for i, (type_name, damage_class) in enumerate(
                itertools.product(["fire", "water", "grass"], ["physical", "special"])
            )
        ]
        result = collapse(pool)
        assert len(result) == 6

    def test_output_is_deterministic(self) -> None:
        pool = [
            move(3, "c", "water", "special", 80),
            move(1, "a", "fire", "physical", 90),
            move(2, "b", "grass", "special", 70),
        ]
        assert [m.name for m in collapse(pool)] == [m.name for m in collapse(list(reversed(pool)))]


class TestShape:
    def test_returns_best_move_objects(self) -> None:
        (result,) = collapse([move(53, "flamethrower", "fire", "special", 90, 95)])
        assert isinstance(result, BestMove)
        assert (result.power, result.accuracy) == (90, 95)

    def test_an_empty_movepool_is_fine(self) -> None:
        """A few Pokemon have no damaging moves at all in the snapshot."""
        assert collapse([]) == []
