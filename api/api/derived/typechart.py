"""Pure type-effectiveness maths.

No database, no network, no cache. Everything here is a function of its inputs,
which is what lets the interesting behaviour -- dual-type multiplication,
immunity, the legal value set -- be tested directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from api.ingest.normalize import CANONICAL_TYPES

# attacking type -> defending type -> multiplier
TypeChart = dict[str, dict[str, float]]

# A single matchup is one of these four. Anything else means the chart is wrong.
LEGAL_CHART_VALUES = frozenset({0.0, 0.5, 1.0, 2.0})

# A dual-typed Pokemon multiplies two of the above, so a defensive multiplier is
# one of these six. 4.0 and 0.25 only exist because of dual typing.
LEGAL_DEFENSIVE_VALUES = frozenset({0.0, 0.25, 0.5, 1.0, 2.0, 4.0})

TYPE_INDEX: dict[str, int] = {name: index for index, name in enumerate(CANONICAL_TYPES)}


def build_chart(rows: Iterable[tuple[str, str, Decimal | float]]) -> TypeChart:
    """Build the nested lookup from (attacking, defending, multiplier) rows.

    Missing pairings default to 1.0 rather than raising, so a partially loaded
    chart degrades to neutral instead of producing a KeyError deep inside a
    request. The 324-row invariant is enforced where the chart is written.
    """
    chart: TypeChart = {
        attacking: dict.fromkeys(CANONICAL_TYPES, 1.0) for attacking in CANONICAL_TYPES
    }
    for attacking, defending, multiplier in rows:
        if attacking in chart and defending in chart[attacking]:
            chart[attacking][defending] = float(multiplier)
    return chart


def matchup(chart: TypeChart, attacking: str, defending: str) -> float:
    """Effectiveness of one attacking type against one defending type."""
    return chart.get(attacking, {}).get(defending, 1.0)


def defensive_multiplier(chart: TypeChart, attacking: str, type1: str, type2: str | None) -> float:
    """How much damage a Pokemon takes from `attacking`, dual typing included.

    Charizard (fire/flying) against rock: 2.0 * 2.0 = 4.0.
    Charizard against grass:              0.5 * 0.5 = 0.25.

    Immunity wins outright, because anything multiplied by zero is zero -- a
    ground move does nothing to a flying type no matter what the other half is.
    """
    total = matchup(chart, attacking, type1)
    if type2 is not None:
        total *= matchup(chart, attacking, type2)
    return total


def defensive_vector(chart: TypeChart, type1: str, type2: str | None) -> list[float]:
    """The 18 defensive multipliers for one Pokemon, in CANONICAL_TYPES order."""
    return [defensive_multiplier(chart, attacking, type1, type2) for attacking in CANONICAL_TYPES]


def explain(chart: TypeChart, attacking: str, type1: str, type2: str | None) -> str:
    """A human-readable derivation, for the debug endpoint."""
    first = matchup(chart, attacking, type1)
    if type2 is None:
        return f"{attacking} vs {type1} = {first:g}"
    second = matchup(chart, attacking, type2)
    return f"{attacking} vs {type1}/{type2} = {first:g} * {second:g} = {first * second:g}"
