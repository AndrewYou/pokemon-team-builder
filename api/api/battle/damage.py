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


# A candidate that moves first effectively lands a fraction of an extra hit
# before taking one. A flat multiplier keeps the score continuous and monotonic;
# modelling turn order exactly would need a discrete simulation whose output is
# a step function, which is what this phase is avoiding.
FIRST_STRIKE_BONUS = 0.15

# A floor on what a turn costs, so an unopposed matchup is not simply "won".
# Without it every candidate that takes zero damage scores exactly 1.0 no
# matter how long it needs to finish, and a one-turn knockout ties with a
# ten-turn grind. Fewer turns is genuinely better -- fewer chances for anything
# to go wrong -- and this keeps the score strictly increasing in outgoing
# damage everywhere, which is the property selection relies on.
TURN_COST = 0.05


def matchup_score(outgoing: float, incoming: float, moves_first: bool) -> float:
    """How good a matchup is, in [0, 1].

    Strictly increasing in `outgoing`, strictly decreasing in `incoming`, and
    higher when moving first. Both directions are required: a candidate dealing
    0.6 a turn while taking 1.2 is not a counter, it is a casualty, and the
    type-only scorer could not tell those apart.
    """
    if outgoing <= 0:
        # Cannot touch it. Nothing about the other direction redeems that.
        return 0.0

    effective = outgoing * (1 + FIRST_STRIKE_BONUS) if moves_first else outgoing
    return effective / (effective + incoming + TURN_COST)
