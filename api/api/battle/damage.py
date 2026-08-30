"""Damage maths. Pure: no I/O, no cache, no database.

The declared simplifications are level 50, no EVs or IVs, a neutral nature, and
the average damage roll. They are choices, not omissions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

LEVEL = 50

# (2 * L) / 5 + 2. Kept as an expression rather than the 22 it evaluates to, so
# the level is a single place to change rather than a magic number to hunt.
LEVEL_TERM = (2 * LEVEL) / 5 + 2

STAB = 1.5

PHYSICAL = "physical"


def hp_at_level_50(base_hp: int) -> int:
    """HP has its own formula, and the +60 is load-bearing.

    Without it every Pokemon has roughly a third of its real health, almost
    every attack reads as a one-hit knockout, and the damage matrix loses the
    discrimination the model exists to provide.
    """
    return base_hp + 60


def stat_at_level_50(base: int) -> int:
    """Every stat other than HP."""
    return base + 5


@dataclass(frozen=True, slots=True)
class DamageResult:
    """One attack, resolved."""

    damage: float
    fraction: float
    stab: float
    multiplier: float
    attack_stat: int
    defense_stat: int

    @property
    def turns_to_ko(self) -> int:
        """For display only. The scorer never sees this."""
        return math.ceil(1 / self.fraction) if self.fraction > 0 else 0


def damage_fraction(
    *,
    power: int,
    damage_class: str,
    move_type: str,
    attacker_types: tuple[str, ...],
    attacker_attack: int,
    attacker_special_attack: int,
    defender_defense: int,
    defender_special_defense: int,
    defender_hp: int,
    type_multiplier: float,
    accuracy: int | None = None,
) -> DamageResult | None:
    """Fraction of the defender's health one hit removes.

    Returns a **continuous fraction**, never a rounded turn count. Rounding to
    turns collapses the whole model into about four values -- 1HKO, 2HKO, 3HKO
    -- which produces *more* ties than the type-only scorer it replaces, and
    hands every one of them to iteration order. 0.51 and 0.55 of a health bar
    are both "2HKO" and are not equally good.

    Returns None for an immunity rather than zero or infinity, so the caller has
    to decide what a matchup with no interaction means instead of letting a zero
    flow into a division.
    """
    if type_multiplier == 0:
        return None

    physical = damage_class == PHYSICAL
    attack = attacker_attack if physical else attacker_special_attack
    defense = defender_defense if physical else defender_special_defense

    stab = STAB if move_type in attacker_types else 1.0

    base = (LEVEL_TERM * power * attack / defense) / 50 + 2
    damage = base * stab * type_multiplier

    # Accuracy folded in as expected damage per turn: a 70%-accurate move that
    # hits harder is not automatically better than a reliable one.
    if accuracy is not None:
        damage *= accuracy / 100

    return DamageResult(
        damage=damage,
        fraction=damage / defender_hp,
        stab=stab,
        multiplier=type_multiplier,
        attack_stat=attack,
        defense_stat=defense,
    )


# Overkill is not extra credit. Dealing 355% of a health bar is not three times
# better than dealing 120%: both are a one-turn knockout. Left uncapped the
# strongest picks compress into a narrow band at the top and the ranking stops
# discriminating between them.
OVERKILL_CAP = 1.2

# A floor on what a turn costs, so an unopposed matchup is not simply "won" and
# a faster win still outscores a slower one.
TURN_COST = 0.05

# Verdict thresholds, defined here so the API and the UI cannot disagree.
DOMINATES_MARGIN = 3
WINS_MARGIN = 1


def turns_to_ko(fraction: float) -> int | None:
    """Turns to knock the defender out, or None if it never happens."""
    return math.ceil(1 / fraction) if fraction > 0 else None


def defender_turns(our_turns: int | None, moves_first: bool) -> int:
    """How many times the defender actually gets to act.

    This is the part a symmetric exchange gets wrong. If we outspeed and knock
    them out in one turn they never attack at all, so charging us for damage we
    will never take penalises exactly the picks that are doing best.
    """
    if our_turns is None:
        # We never knock them out, so they keep attacking. One turn's worth is
        # the honest unit to compare against.
        return 1
    return max(0, our_turns - 1) if moves_first else our_turns


def matchup_score(outgoing: float, incoming: float, moves_first: bool) -> float:
    """How good a matchup is, in [0, 1]. The sort key, not a display value.

    Increasing in outgoing damage up to the overkill cap, decreasing in the
    damage actually taken over the exchange, and higher when moving first --
    because moving first removes turns from the opponent rather than adding a
    bonus to us.
    """
    if outgoing <= 0:
        # Cannot touch it. Nothing about the other direction redeems that.
        return 0.0

    capped = min(outgoing, OVERKILL_CAP)
    taken = incoming * defender_turns(turns_to_ko(outgoing), moves_first)
    return capped / (capped + taken + TURN_COST)


def turn_margin(outgoing: float, incoming: float, moves_first: bool) -> int | None:
    """Turns to spare we win the 1v1 by. None when the question is undefined.

    A signed integer a person can read at a glance: +3 says they would need
    three more turns to knock us out than we need for them. The 0-1 score sorts
    well and communicates nothing.

    The speed adjustment costs a turn when we are SLOWER, not when we are
    faster. Both sides act on every round; speed only decides who resolves
    first within it, so the slower Pokemon loses a tie. Subtracting the turn
    from the faster side instead reports a pick that knocks the enemy out
    before it ever moves as losing by one.
    """
    ours = turns_to_ko(outgoing)
    theirs = turns_to_ko(incoming)
    if ours is None or theirs is None:
        # One side cannot finish the other, so a difference of turns has no
        # meaning. The caller renders these as "Can't KO" or "Never KOs us"
        # rather than as a very large number.
        return None
    return theirs - ours - (0 if moves_first else 1)


def verdict(margin: int | None, can_ko: bool, can_be_koed: bool) -> str:
    """A word for the matchup, thresholds shared with the UI."""
    if not can_ko:
        return "Loses"
    if not can_be_koed:
        return "Dominates"
    if margin is None:
        return "Trades"
    if margin >= DOMINATES_MARGIN:
        return "Dominates"
    if margin >= WINS_MARGIN:
        return "Wins"
    return "Trades" if margin == 0 else "Loses"
