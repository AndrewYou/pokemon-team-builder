"""Tests for the damage model.

The formula is the foundation everything above it rests on, so the headline
cases are computed by hand rather than snapshotted from the implementation --
a snapshot of a wrong formula passes forever.
"""

from __future__ import annotations

import pytest

from api.battle.damage import (
    LEVEL,
    LEVEL_TERM,
    OVERKILL_CAP,
    DamageResult,
    damage_fraction,
    defender_turns,
    hp_at_level_50,
    matchup_score,
    stat_at_level_50,
    turn_margin,
    turns_to_ko,
    verdict,
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

    def test_increasing_in_outgoing(self) -> None:
        previous = -1.0
        for outgoing in [0.1, 0.2, 0.4, 0.8, 1.1]:
            value = matchup_score(outgoing, 0.5, False)
            assert value > previous
            previous = value

    def test_overkill_is_capped(self) -> None:
        """355% of a health bar is not three times better than 120%. Both are a
        one-turn knockout, and left uncapped the strongest picks compress into a
        narrow band where the ranking stops discriminating."""
        assert matchup_score(1.3, 0.3, False) == matchup_score(3.6, 0.3, False)
        assert OVERKILL_CAP < 1.3

    def test_strictly_decreasing_in_incoming(self) -> None:
        previous = 2.0
        for incoming in [0.1, 0.2, 0.4, 0.8, 1.6]:
            value = matchup_score(0.5, incoming, False)
            assert value < previous
            previous = value

    def test_moving_first_is_rewarded(self) -> None:
        assert matchup_score(0.5, 0.5, True) > matchup_score(0.5, 0.5, False)

    def test_outspeeding_a_one_shot_takes_nothing(self) -> None:
        """The case the symmetric formula got wrong: a pick that outspeeds and
        knocks the enemy out in one turn was still charged for damage it never
        takes, so exactly the picks doing best were penalised."""
        assert matchup_score(1.5, 2.0, True) == pytest.approx(matchup_score(1.5, 0.0, True))

    def test_a_candidate_that_cannot_damage_scores_zero(self) -> None:
        assert matchup_score(0.0, 0.5, True) == 0.0

    def test_taking_nothing_back_approaches_one(self) -> None:
        """Approaches, not reaches: a matchup still costs turns."""
        assert 0.9 < matchup_score(1.2, 0.0, False) < 1.0
        assert matchup_score(1.2, 0.0, False) > matchup_score(0.3, 0.0, False)

    def test_dealing_less_than_it_takes_scores_below_half(self) -> None:
        """0.6 out against 1.2 in is not a counter, it is a casualty -- the
        distinction type effectiveness alone could not make."""
        assert matchup_score(0.6, 1.2, False) < 0.5


class TestMonotonicity:
    """The properties selection depends on. If score() were not monotonic in
    outgoing damage, marginal gain would reward the wrong candidate and the
    whole loop above it would be sound but useless."""

    @pytest.mark.parametrize("incoming", [0.0, 0.1, 0.5, 1.0, 2.0])
    @pytest.mark.parametrize("moves_first", [True, False])
    def test_never_decreasing_in_outgoing(self, incoming: float, moves_first: bool) -> None:
        """Non-decreasing rather than strictly increasing: the overkill cap
        flattens the top deliberately, and crossing a turn threshold can only
        help."""
        scores = [
            matchup_score(out, incoming, moves_first)
            for out in [0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
        ]
        assert all(later >= earlier for earlier, later in zip(scores, scores[1:], strict=False))

    @pytest.mark.parametrize("incoming", [0.1, 0.5, 1.0])
    def test_strictly_increasing_below_the_cap(self, incoming: float) -> None:
        scores = [matchup_score(out, incoming, False) for out in [0.05, 0.1, 0.2, 0.4, 0.8, 1.0]]
        assert all(later > earlier for earlier, later in zip(scores, scores[1:], strict=False))

    @pytest.mark.parametrize("outgoing", [0.1, 0.3, 0.5])
    @pytest.mark.parametrize("moves_first", [True, False])
    def test_never_increasing_in_incoming(self, outgoing: float, moves_first: bool) -> None:
        scores = [
            matchup_score(outgoing, inc, moves_first)
            for inc in [0.0, 0.05, 0.1, 0.3, 0.6, 1.0, 2.0, 4.0]
        ]
        assert all(later <= earlier for earlier, later in zip(scores, scores[1:], strict=False))

    def test_incoming_stops_mattering_when_it_never_lands(self) -> None:
        """Outspeeding a one-shot means they never act, so how hard they hit is
        irrelevant. This is the fix, not a flaw: the old symmetric formula
        penalised exactly the picks that were winning cleanest."""
        assert matchup_score(1.5, 0.1, True) == matchup_score(1.5, 9.9, True)

    @pytest.mark.parametrize("outgoing", [0.1, 0.5, 1.0, 2.0])
    @pytest.mark.parametrize("incoming", [0.1, 0.5, 1.0, 2.0])
    def test_moving_first_never_hurts(self, outgoing: float, incoming: float) -> None:
        assert matchup_score(outgoing, incoming, True) >= matchup_score(outgoing, incoming, False)

    def test_stays_bounded_across_extremes(self) -> None:
        for outgoing in [0.001, 1.0, 50.0]:
            for incoming in [0.0, 1.0, 50.0]:
                value = matchup_score(outgoing, incoming, True)
                assert 0.0 <= value <= 1.0


class TestTurnMargin:
    """The number a person reads. +3 says they run out of attacks three short;
    0.84 says nothing.

    Margin counts the enemy's ATTACKS, not either side's turns-to-KO, and speed
    is applied once by removing an attack from them. Adjusting turns-to-KO
    instead is invisible whenever ceil() has already put both sides at one turn,
    which is most of the interesting matchups.
    """

    def test_a_clean_outspeed_one_shot(self) -> None:
        # We KO in 1 and move first, so they never attack. They needed 3.
        assert turn_margin(1.5, 0.4, True) == 3

    def test_being_slower_gives_them_the_attack_back(self) -> None:
        assert turn_margin(1.5, 0.4, False) == 2

    def test_outspeeding_a_mutual_one_shot_is_a_win(self) -> None:
        """Both sides KO in one turn. Moving first, they never act at all.

        This is the case the old formula got wrong: ceil() collapses both sides
        to a single turn, so subtracting a turn from their KO count produced 0
        -- "Trades" -- for the single most dominant outcome in the game.
        """
        assert turn_margin(1.5, 1.5, True) == 1

    def test_being_slower_in_a_mutual_one_shot_is_not_a_win(self) -> None:
        """They land exactly the one attack they need, before we act."""
        assert turn_margin(1.5, 1.5, False) == 0

    def test_speed_is_worth_exactly_one_attack(self) -> None:
        """Never two, and never zero. The whole bug was applying it twice over."""
        for outgoing in (0.3, 0.51, 1.0, 1.5, 3.3):
            fast = turn_margin(outgoing, 0.4, True)
            slow = turn_margin(outgoing, 0.4, False)
            assert fast is not None and slow is not None
            assert fast - slow == 1

    def test_negative_when_we_lose_the_exchange(self) -> None:
        margin = turn_margin(0.2, 1.5, False)
        assert margin is not None and margin < 0

    def test_is_an_integer(self) -> None:
        value = turn_margin(0.37, 0.21, True)
        assert isinstance(value, int)

    def test_undefined_when_we_cannot_ko(self) -> None:
        """Not a huge number: the caller renders this as "Can't KO"."""
        assert turn_margin(0.0, 0.5, False) is None

    def test_undefined_when_they_cannot_ko(self) -> None:
        """Immunity. their_turns is infinite, so the margin is unbounded and
        the caller says "Never KOs us" rather than printing a number."""
        assert turn_margin(0.5, 0.0, False) is None

    def test_margin_agrees_with_the_scorer_about_who_acted(self) -> None:
        """Margin and score both read `defender_turns`, so they cannot drift."""
        for outgoing in (0.3, 0.6, 1.2, 2.0):
            for moves_first in (True, False):
                ours = turns_to_ko(outgoing)
                assert ours is not None
                acted = defender_turns(ours, moves_first)
                theirs = turns_to_ko(0.35)
                assert theirs is not None
                assert turn_margin(outgoing, 0.35, moves_first) == theirs - acted


class TestVerdict:
    @pytest.mark.parametrize(
        ("margin", "expected"),
        [
            (5, "Dominates"),
            (3, "Dominates"),
            (2, "Wins"),
            (1, "Wins"),
            (0, "Trades"),
            (-1, "Loses"),
        ],
    )
    def test_thresholds(self, margin: int, expected: str) -> None:
        assert verdict(margin, can_ko=True, can_be_koed=True) == expected

    def test_cannot_be_koed_dominates(self) -> None:
        assert verdict(None, can_ko=True, can_be_koed=False) == "Dominates"

    def test_cannot_ko_loses(self) -> None:
        assert verdict(None, can_ko=False, can_be_koed=True) == "Loses"

    def test_untouched_dominates_however_narrow_the_margin(self) -> None:
        """Taking zero damage is domination even at +1.

        Against something that would also KO in one turn, the best possible
        outcome scores +1 on the margin -- the same as a scrappy win -- because
        ceil() cannot represent anything finer. The enemy landing no attacks at
        all is the distinction the number cannot carry.
        """
        assert verdict(1, can_ko=True, can_be_koed=True, untouched=True) == "Dominates"
        assert verdict(1, can_ko=True, can_be_koed=True) == "Wins"

    def test_untouched_does_not_rescue_a_pick_that_cannot_ko(self) -> None:
        assert verdict(None, can_ko=False, can_be_koed=True, untouched=True) == "Loses"

    def test_sign_matches_the_verdict(self) -> None:
        """The badge and the number must never disagree."""
        for margin in range(-5, 6):
            word = verdict(margin, can_ko=True, can_be_koed=True)
            if margin > 0:
                assert word in {"Wins", "Dominates"}
            elif margin == 0:
                assert word == "Trades"
            else:
                assert word == "Loses"
