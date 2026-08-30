"""Tests for the damage model.

The formula is the foundation everything above it rests on, so the headline
cases are computed by hand rather than snapshotted from the implementation --
a snapshot of a wrong formula passes forever.
"""

from __future__ import annotations

import pytest

from api.battle.damage import (
    FIRST_STRIKE_BONUS,
    LEVEL,
    LEVEL_TERM,
    TURN_COST,
    DamageResult,
    damage_fraction,
    hp_at_level_50,
    matchup_score,
    stat_at_level_50,
)


class TestLevelFifty:
    def test_level_term(self) -> None:
        assert LEVEL == 50
        assert LEVEL_TERM == 22

    def test_hp_adds_sixty(self) -> None:
        """Charizard's 78 base HP is 138 at level 50."""
        assert hp_at_level_50(78) == 138

    def test_other_stats_add_five(self) -> None:
        assert stat_at_level_50(109) == 114

    def test_the_hp_formula_differs_from_the_rest(self) -> None:
        """Using +5 for HP would leave everything on roughly a third of its
        health, so every attack reads as a one-hit knockout and the matrix
        loses all discrimination."""
        assert hp_at_level_50(100) != stat_at_level_50(100)


class TestHandComputed:
    def test_charizard_flamethrower_into_venusaur(self) -> None:
        """Charizard SpA 109 -> 114. Venusaur SpD 100 -> 105, HP 80 -> 140.
        Flamethrower is 90 power, special, fire: STAB 1.5, and fire is 2x into
        grass and 1x into poison.

            base   = (22 * 90 * 114 / 105) / 50 + 2 = 44.994...
            damage = base * 1.5 * 2                 = 134.98...
        """
        result = damage_fraction(
            power=90,
            damage_class="special",
            move_type="fire",
            attacker_types=("fire", "flying"),
            attacker_attack=stat_at_level_50(84),
            attacker_special_attack=stat_at_level_50(109),
            defender_defense=stat_at_level_50(83),
            defender_special_defense=stat_at_level_50(100),
            defender_hp=hp_at_level_50(80),
            type_multiplier=2.0,
        )
        assert result is not None
        expected_base = (LEVEL_TERM * 90 * 114 / 105) / 50 + 2
        assert result.damage == pytest.approx(expected_base * 1.5 * 2.0)
        assert result.fraction == pytest.approx(expected_base * 3.0 / 140)
        assert result.turns_to_ko == 2

    def test_a_neutral_unboosted_hit(self) -> None:
        """No STAB, neutral effectiveness: the modifiers drop out entirely."""
        result = damage_fraction(
            power=100,
            damage_class="physical",
            move_type="normal",
            attacker_types=("water",),
            attacker_attack=105,
            attacker_special_attack=50,
            defender_defense=105,
            defender_special_defense=50,
            defender_hp=200,
            type_multiplier=1.0,
        )
        assert result is not None
        # A/D is exactly 1, so base = (22 * 100) / 50 + 2 = 46.
        assert result.damage == pytest.approx(46.0)
        assert result.fraction == pytest.approx(0.23)


class TestStab:
    def _run(self, move_type: str, attacker_types: tuple[str, ...]) -> float:
        result = damage_fraction(
            power=100,
            damage_class="physical",
            move_type=move_type,
            attacker_types=attacker_types,
            attacker_attack=100,
            attacker_special_attack=100,
            defender_defense=100,
            defender_special_defense=100,
            defender_hp=200,
            type_multiplier=1.0,
        )
        assert result is not None
        return result.damage

    def test_applied_on_the_primary_type(self) -> None:
        assert self._run("fire", ("fire", "flying")) == pytest.approx(
            self._run("water", ("fire",)) * 1.5
        )

    def test_applied_on_the_secondary_type(self) -> None:
        assert self._run("flying", ("fire", "flying")) == pytest.approx(
            self._run("water", ("fire", "flying")) * 1.5
        )

    def test_not_applied_otherwise(self) -> None:
        result = damage_fraction(
            power=100,
            damage_class="physical",
            move_type="water",
            attacker_types=("fire",),
            attacker_attack=100,
            attacker_special_attack=100,
            defender_defense=100,
            defender_special_defense=100,
            defender_hp=200,
            type_multiplier=1.0,
        )
        assert result is not None and result.stab == 1.0


class TestStatPairing:
    """Physical uses attack against defense, special uses special attack
    against special defense. Crossing them is a silent, plausible-looking
    error: the numbers stay in range and every matchup is wrong."""

    def _result(self, damage_class: str) -> DamageResult | None:
        return damage_fraction(
            power=100,
            damage_class=damage_class,
            move_type="normal",
            attacker_types=("normal",),
            attacker_attack=150,
            attacker_special_attack=50,
            defender_defense=60,
            defender_special_defense=200,
            defender_hp=200,
            type_multiplier=1.0,
        )

    def test_physical_uses_attack_and_defense(self) -> None:
        result = self._result("physical")
        assert result is not None
        assert (result.attack_stat, result.defense_stat) == (150, 60)

    def test_special_uses_special_attack_and_special_defense(self) -> None:
        result = self._result("special")
        assert result is not None
        assert (result.attack_stat, result.defense_stat) == (50, 200)

    def test_the_pairs_are_never_crossed(self) -> None:
        physical = self._result("physical")
        special = self._result("special")
        assert physical is not None and special is not None
        # Crossing would pair 150 with 200 or 50 with 60.
        assert {physical.attack_stat, physical.defense_stat} == {150, 60}
        assert {special.attack_stat, special.defense_stat} == {50, 200}


class TestImmunity:
    def test_returns_none_rather_than_zero_or_infinity(self) -> None:
        """None forces the caller to decide what "no interaction" means instead
        of letting a zero flow into a division."""
        assert (
            damage_fraction(
                power=100,
                damage_class="physical",
                move_type="normal",
                attacker_types=("normal",),
                attacker_attack=100,
                attacker_special_attack=100,
                defender_defense=100,
                defender_special_defense=100,
                defender_hp=200,
                type_multiplier=0.0,
            )
            is None
        )


class TestAccuracy:
    def test_folded_in_as_expected_damage(self) -> None:
        full = damage_fraction(
            power=100,
            damage_class="physical",
            move_type="normal",
            attacker_types=("normal",),
            attacker_attack=100,
            attacker_special_attack=100,
            defender_defense=100,
            defender_special_defense=100,
            defender_hp=200,
            type_multiplier=1.0,
            accuracy=100,
        )
        shaky = damage_fraction(
            power=100,
            damage_class="physical",
            move_type="normal",
            attacker_types=("normal",),
            attacker_attack=100,
            attacker_special_attack=100,
            defender_defense=100,
            defender_special_defense=100,
            defender_hp=200,
            type_multiplier=1.0,
            accuracy=70,
        )
        assert full is not None and shaky is not None
        assert shaky.damage == pytest.approx(full.damage * 0.7)


class TestContinuousFraction:
    """The fraction is the whole point. Rounding to turns collapses the model
    into about four values, which produces more ties than the type-only scorer
    it replaced and hands each one to iteration order."""

    def test_two_matchups_in_the_same_turn_count_still_differ(self) -> None:
        def run(power: int) -> float:
            result = damage_fraction(
                power=power,
                damage_class="physical",
                move_type="normal",
                attacker_types=("normal",),
                attacker_attack=100,
                attacker_special_attack=100,
                defender_defense=100,
                defender_special_defense=100,
                defender_hp=100,
                type_multiplier=1.0,
            )
            assert result is not None
            return result.fraction

        weaker, stronger = run(100), run(110)
        assert weaker != stronger
        # Both are two-hit knockouts, and they are not equally good.
        import math

        assert math.ceil(1 / weaker) == math.ceil(1 / stronger) == 2


class TestMatchupScore:
    def test_bounded(self) -> None:
        assert 0 <= matchup_score(0.5, 0.5, False) <= 1

    def test_strictly_increasing_in_outgoing(self) -> None:
        previous = -1.0
        for outgoing in [0.1, 0.2, 0.4, 0.8, 1.6]:
            value = matchup_score(outgoing, 0.5, False)
            assert value > previous
            previous = value

    def test_strictly_decreasing_in_incoming(self) -> None:
        previous = 2.0
        for incoming in [0.1, 0.2, 0.4, 0.8, 1.6]:
            value = matchup_score(0.5, incoming, False)
            assert value < previous
            previous = value

    def test_moving_first_is_rewarded(self) -> None:
        assert matchup_score(0.5, 0.5, True) > matchup_score(0.5, 0.5, False)
        assert FIRST_STRIKE_BONUS > 0

    def test_a_candidate_that_cannot_damage_scores_zero(self) -> None:
        assert matchup_score(0.0, 0.5, True) == 0.0

    def test_taking_nothing_back_approaches_one(self) -> None:
        """Approaches, not reaches: an unopposed matchup still costs turns, so a
        faster win outscores a slower one instead of tying at exactly 1."""
        assert 0.9 < matchup_score(5.0, 0.0, False) < 1.0
        assert matchup_score(5.0, 0.0, False) > matchup_score(0.5, 0.0, False)

    def test_dealing_less_than_it_takes_scores_below_half(self) -> None:
        """0.6 out against 1.2 in is not a counter, it is a casualty -- the
        distinction type effectiveness alone could not make."""
        assert matchup_score(0.6, 1.2, False) < 0.5


class TestMonotonicity:
    """The property the selection algorithm depends on. If score() were not
    monotonic in outgoing damage, marginal gain would reward the wrong
    candidate and the whole loop above it would be sound but useless."""

    @pytest.mark.parametrize("incoming", [0.0, 0.1, 0.5, 1.0, 2.0])
    @pytest.mark.parametrize("moves_first", [True, False])
    def test_strictly_increasing_in_outgoing(self, incoming: float, moves_first: bool) -> None:
        scores = [
            matchup_score(out, incoming, moves_first)
            for out in [0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
        ]
        assert all(later > earlier for earlier, later in zip(scores, scores[1:], strict=False))

    @pytest.mark.parametrize("outgoing", [0.1, 0.5, 1.0, 2.0])
    @pytest.mark.parametrize("moves_first", [True, False])
    def test_strictly_decreasing_in_incoming(self, outgoing: float, moves_first: bool) -> None:
        scores = [
            matchup_score(outgoing, inc, moves_first)
            for inc in [0.0, 0.05, 0.1, 0.3, 0.6, 1.0, 2.0, 4.0]
        ]
        assert all(later < earlier for earlier, later in zip(scores, scores[1:], strict=False))

    @pytest.mark.parametrize("outgoing", [0.1, 0.5, 1.0, 2.0])
    @pytest.mark.parametrize("incoming", [0.1, 0.5, 1.0, 2.0])
    def test_moving_first_never_hurts(self, outgoing: float, incoming: float) -> None:
        assert matchup_score(outgoing, incoming, True) >= matchup_score(outgoing, incoming, False)

    def test_the_turn_cost_is_what_makes_it_strict(self) -> None:
        """Without it, every matchup taking zero damage scores exactly 1.0 and
        a one-turn knockout is indistinguishable from a ten-turn one."""
        assert TURN_COST > 0
        assert matchup_score(2.0, 0.0, False) > matchup_score(1.0, 0.0, False)

    def test_stays_bounded_across_extremes(self) -> None:
        for outgoing in [0.001, 1.0, 50.0]:
            for incoming in [0.0, 1.0, 50.0]:
                value = matchup_score(outgoing, incoming, True)
                assert 0.0 <= value <= 1.0
