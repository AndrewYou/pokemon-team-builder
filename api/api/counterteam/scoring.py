"""Counter-team scoring and selection.

Type effectiveness only. No damage formula, no stats, no moves, no speed --
those arrive in phase 9, which replaces `score` and nothing else.

Everything here runs off the in-memory derived cache. No database access, no
persistence: a request is a pure function of the enemy ids and the cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from api.battle.damage import (
    LEVEL_TERM,
    OVERKILL_CAP,
    TURN_COST,
    damage_fraction,
    matchup_score,
    turn_margin,
    turns_to_ko,
    verdict,
)
from api.derived.cache import DerivedCache, PokemonMeta

# The game's roster limit, used only to reject an oversized request. The
# number of picks is never this -- it is derived from the enemy team.
MAX_TEAM_SIZE = 6

# A candidate immune to everything the enemy's types can throw is strictly
# better off than one merely resisting at 0.25x, so it sits one step further up
# the same scale. A literal 1/0 would be infinity, which is neither comparable
# nor JSON-serialisable.
IMMUNE_DEFENSE = 8.0


@dataclass(frozen=True, slots=True)
class Matchup:
    """One candidate measured against one enemy, with the reasoning kept."""

    score: float
    outgoing: float
    incoming: float
    move_name: str
    move_type: str
    damage_class: str
    outspeeds: bool

    @property
    def our_turns(self) -> int | None:
        """Turns we need. None when we cannot knock them out at all."""
        return turns_to_ko(self.outgoing)

    @property
    def their_turns(self) -> int | None:
        """Turns they need to knock us out. None when they never can.

        Reported raw. The speed adjustment lives in `margin`, so this stays a
        plain answer to "how many hits can we survive".
        """
        return turns_to_ko(self.incoming)

    @property
    def margin(self) -> int | None:
        return turn_margin(self.outgoing, self.incoming, self.outspeeds)

    @property
    def verdict(self) -> str:
        return verdict(self.margin, self.outgoing > 0, self.incoming > 0)

    @property
    def incoming_over_exchange(self) -> float:
        """Damage we actually take, not the per-turn rate.

        Zero when we outspeed and knock them out in one turn, because they
        never get to attack.
        """
        from api.battle.damage import defender_turns

        return self.incoming * defender_turns(self.our_turns, self.outspeeds)


def candidate_type_mask(cache: DerivedCache) -> npt.NDArray[np.bool_]:
    """[candidate, type] -> does this candidate have that type.

    Used by selection to prefer typings the team does not already cover.
    """
    mask = np.zeros((len(cache.meta), cache.vectors.shape[1]), dtype=bool)
    for row, meta in enumerate(cache.meta):
        for type_name in meta.types:
            mask[row, cache.type_index[type_name]] = True
    return mask


def _valid(cache: DerivedCache) -> npt.NDArray[np.bool_]:
    """Padding columns carry power 0. The +2 in the damage formula means they
    would otherwise contribute real damage rather than none."""
    return cache.move_power > 0


def outgoing_against(
    cache: DerivedCache, defender_row: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.intp]]:
    """Every candidate's best damage fraction against one defender.

    Broadcast over the padded movepool arrays: 1025 x 36 in one pass rather
    than a Python loop per candidate per move.
    """
    defender_vector = cache.vectors[defender_row]
    multiplier = defender_vector[cache.move_type_index]

    attack = np.where(cache.move_physical, cache.stats[:, 1:2], cache.stats[:, 3:4])
    defense = np.where(
        cache.move_physical, cache.stats[defender_row, 2], cache.stats[defender_row, 4]
    )

    base = (LEVEL_TERM * cache.move_power * attack / defense) / 50 + 2
    damage = base * cache.move_stab * multiplier * cache.move_accuracy
    damage = np.where(_valid(cache), damage, 0.0)

    fractions = damage / cache.stats[defender_row, 0]
    return fractions.max(axis=1), fractions.argmax(axis=1)


def incoming_from(cache: DerivedCache, attacker_row: int) -> npt.NDArray[np.float64]:
    """One attacker's best damage fraction against every candidate."""
    types = cache.move_type_index[attacker_row]
    powers = cache.move_power[attacker_row]
    physical = cache.move_physical[attacker_row]

    multiplier = cache.vectors[:, types]
    attack = np.where(physical, cache.stats[attacker_row, 1], cache.stats[attacker_row, 3])
    defense = np.where(physical[np.newaxis, :], cache.stats[:, 2:3], cache.stats[:, 4:5])

    base = (LEVEL_TERM * powers[np.newaxis, :] * attack[np.newaxis, :] / defense) / 50 + 2
    damage = base * cache.move_stab[attacker_row] * multiplier * cache.move_accuracy[attacker_row]
    damage = np.where(powers[np.newaxis, :] > 0, damage, 0.0)

    fractions = damage / cache.stats[:, 0:1]
    return fractions.max(axis=1)


def score(cache: DerivedCache, candidate_row: int, enemy_row: int) -> Matchup:
    """Score one candidate against one enemy.

    THE function this phase replaced. Selection, marginal gain, the round count
    and the response shape are all untouched above it.

        outgoing = best damage fraction this candidate lands per turn
        incoming = best damage fraction it takes per turn
        score    = outgoing / (outgoing + incoming), with a bonus for striking
                   first

    Both directions matter. Type effectiveness alone could not tell a counter
    from a casualty: dealing 0.6 a turn while taking 1.2 is losing.
    """
    outgoing_all, move_index = outgoing_against(cache, enemy_row)
    outgoing = float(outgoing_all[candidate_row])
    incoming = float(incoming_from(cache, enemy_row)[candidate_row])
    outspeeds = bool(cache.stats[candidate_row, 5] > cache.stats[enemy_row, 5])

    moves = cache.moves[candidate_row]
    chosen = moves[int(move_index[candidate_row])] if moves and outgoing > 0 else None

    return Matchup(
        score=matchup_score(outgoing, incoming, outspeeds),
        outgoing=outgoing,
        incoming=incoming,
        move_name=chosen.name if chosen else "",
        move_type=chosen.type if chosen else "",
        damage_class=chosen.damage_class if chosen else "",
        outspeeds=outspeeds,
    )


@dataclass(slots=True)
class ScoreGrid:
    """Every candidate against every enemy, plus the detail the response needs."""

    scores: npt.NDArray[np.float64]
    outgoing: npt.NDArray[np.float64]
    incoming: npt.NDArray[np.float64]
    move_index: npt.NDArray[np.intp]
    outspeeds: npt.NDArray[np.bool_]


def score_matrix(cache: DerivedCache, enemy_rows: list[int]) -> ScoreGrid:
    """Score every candidate against every enemy at once.

    Selection needs the whole grid anyway, and 1025 candidates by six enemies
    is a handful of array operations rather than 6150 Python calls.
    """
    count = len(cache.meta)
    shape = (count, len(enemy_rows))
    outgoing = np.zeros(shape, dtype=np.float64)
    incoming = np.zeros(shape, dtype=np.float64)
    move_index = np.zeros(shape, dtype=np.intp)
    outspeeds = np.zeros(shape, dtype=bool)

    for column, enemy_row in enumerate(enemy_rows):
        best, chosen = outgoing_against(cache, enemy_row)
        outgoing[:, column] = best
        move_index[:, column] = chosen
        incoming[:, column] = incoming_from(cache, enemy_row)
        outspeeds[:, column] = cache.stats[:, 5] > cache.stats[enemy_row, 5]

    # The vectorised form of matchup_score. Duplicated rather than called per
    # element, so the constants come from the same place and a test asserts the
    # two paths agree on every pair.
    with np.errstate(invalid="ignore", divide="ignore"):
        our_turns = np.where(outgoing > 0, np.ceil(1 / np.where(outgoing > 0, outgoing, 1)), 0)
    # Moving first removes a turn from them rather than adding a bonus to us,
    # so a pick that outspeeds and one-shots takes nothing at all.
    their_turns = np.where(outspeeds, np.maximum(0, our_turns - 1), our_turns)
    taken = incoming * their_turns

    capped = np.minimum(outgoing, OVERKILL_CAP)
    with np.errstate(invalid="ignore", divide="ignore"):
        scores = np.where(outgoing > 0, capped / (capped + taken + TURN_COST), 0.0)

    return ScoreGrid(
        scores=scores,
        outgoing=outgoing,
        incoming=incoming,
        move_index=move_index,
        outspeeds=outspeeds,
    )


def select_team(
    scores: npt.NDArray[np.float64],
    size: int,
    type_mask: npt.NDArray[np.bool_] | None = None,
    stat_totals: npt.NDArray[np.float64] | None = None,
    ids: npt.NDArray[np.int64] | None = None,
) -> list[int]:
    """Pick `size` counters by marginal gain over what is already covered.

    `size` is required rather than defaulted. A default is what made every
    request return six picks regardless of how many Pokemon it was answering:
    the caller simply never passed one.

    Each round scores every remaining candidate by how much it *improves* the
    current best answer for each enemy, summed across enemies, and takes the
    largest. Clamping each term at zero is what makes it marginal: a candidate
    that is merely adequate against an enemy already well covered contributes
    nothing for that enemy. Diminishing returns falls out of this structure --
    there is deliberately no decay parameter.

    Two rounds can saturate: against three Fire types, one good Rock answers
    all three and every remaining candidate has a marginal gain of zero. Ranking
    those by raw score returns three near-identical Pokemon, which is a fragile
    team and useless advice. So once coverage is saturated the ranking switches
    to breadth of typing first. That is a tie-break among candidates that answer
    the enemy team equally well, not a decay applied to the scoring.
    """
    candidate_count, enemy_count = scores.shape
    best = np.zeros(enemy_count, dtype=np.float64)
    # Base stat totals decide ties, falling back to overall answer quality when
    # the caller has not supplied them.
    totals = stat_totals if stat_totals is not None else scores.sum(axis=1)
    chosen: list[int] = []

    for _ in range(min(size, candidate_count)):
        gains = np.maximum(scores - best, 0.0).sum(axis=1)
        if chosen:
            # Never pick the same Pokemon twice.
            gains[chosen] = -np.inf

        best_gain = gains.max() if gains.size else -np.inf
        if not np.isfinite(best_gain):
            break

        if best_gain > 0:
            # Still covering new ground: gain decides, breadth breaks ties.
            pool = np.flatnonzero(gains >= best_gain - 1e-9)
        else:
            # Saturated. Every remaining candidate adds the same nothing to
            # coverage, so the useful axis is what the team cannot yet hit.
            pool = np.flatnonzero(np.isfinite(gains))
            if pool.size == 0:
                break

        pick = _rank(pool, chosen, totals, type_mask, ids)
        chosen.append(pick)
        best = np.maximum(best, scores[pick])

    return chosen


def _rank(
    pool: npt.NDArray[np.intp],
    chosen: list[int],
    totals: npt.NDArray[np.float64],
    type_mask: npt.NDArray[np.bool_] | None,
    ids: npt.NDArray[np.int64] | None = None,
) -> int:
    """Choose from `pool`, breaking ties deterministically.

    Order: typings the team does not already have, then base stat total
    descending, then id ascending. The last one is not cosmetic -- without it
    iteration order decides ties, and a test that depends on which of two
    equally-scored Pokemon is picked fails intermittently.
    """
    candidates = pool
    if type_mask is not None and chosen:
        covered = type_mask[chosen].any(axis=0)
        novelty = (type_mask[candidates] & ~covered).sum(axis=1)
        candidates = candidates[novelty == novelty.max()]

    best_total = totals[candidates].max()
    candidates = candidates[totals[candidates] == best_total]

    if ids is None:
        return int(candidates[0])
    return int(candidates[np.argmin(ids[candidates])])


def _title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def rationale(cache: DerivedCache, candidate_row: int, enemy_row: int, matchup: Matchup) -> str:
    """Explain a matchup without leaving who-takes-what ambiguous.

    The old wording -- "takes 355% per turn ... takes 74% back" -- used the same
    verb for both directions and reported damage the pick never actually takes
    when it outspeeds and one-shots.
    """
    candidate = cache.meta[candidate_row]
    enemy = cache.meta[enemy_row]

    if matchup.outgoing <= 0:
        return f"{_title(candidate.name)} cannot damage {'/'.join(enemy.types)}"

    move = f"{_title(matchup.move_name)} ({_title(matchup.move_type)})"
    parts = [f"{move} — deals {matchup.outgoing:.0%} per turn, KOs in {matchup.our_turns}"]

    if matchup.outspeeds:
        # Report what is actually taken, not the hypothetical: a pick that
        # outspeeds and one-shots takes nothing.
        parts.append(f"moves first, takes {matchup.incoming_over_exchange:.0%} back")
    else:
        parts.append(f"takes {matchup.incoming_over_exchange:.0%} back")

    return "; ".join(parts)


def meta_of(cache: DerivedCache, row: int) -> PokemonMeta:
    return cache.meta[row]


def explain_matchup(cache: DerivedCache, attacker_row: int, defender_row: int) -> dict[str, Any]:
    """Every number behind one pairing, for the debug endpoint.

    Recomputed through the scalar path rather than read out of the grid, so a
    disagreement between the two shows up here rather than staying hidden.
    """
    fractions, indices = outgoing_against(cache, defender_row)
    fraction = float(fractions[attacker_row])
    moves = cache.moves[attacker_row]
    move = moves[int(indices[attacker_row])] if moves and fraction > 0 else None

    attacker = cache.meta[attacker_row]
    defender = cache.meta[defender_row]
    physical = move.damage_class == "physical" if move else True

    detail = damage_fraction(
        power=move.power if move else 0,
        damage_class=move.damage_class if move else "physical",
        move_type=move.type if move else "normal",
        attacker_types=attacker.types,
        attacker_attack=int(cache.stats[attacker_row, 1]),
        attacker_special_attack=int(cache.stats[attacker_row, 3]),
        defender_defense=int(cache.stats[defender_row, 2]),
        defender_special_defense=int(cache.stats[defender_row, 4]),
        defender_hp=int(cache.stats[defender_row, 0]),
        type_multiplier=(cache.vectors[defender_row][cache.type_index[move.type]] if move else 0.0),
        accuracy=move.accuracy if move else None,
    )

    return {
        "attacker_id": attacker.id,
        "attacker_name": attacker.name,
        "attacker_types": list(attacker.types),
        "defender_id": defender.id,
        "defender_name": defender.name,
        "defender_types": list(defender.types),
        "move_name": move.name if move else "",
        "move_type": move.type if move else "",
        "damage_class": move.damage_class if move else "",
        "move_power": move.power if move else 0,
        "move_accuracy": move.accuracy if move else None,
        "attack_stat": int(cache.stats[attacker_row, 1 if physical else 3]),
        "defense_stat": int(cache.stats[defender_row, 2 if physical else 4]),
        "defender_hp": int(cache.stats[defender_row, 0]),
        "stab": detail.stab if detail else 0.0,
        "type_multiplier": detail.multiplier if detail else 0.0,
        "raw_damage": round(detail.damage, 4) if detail else 0.0,
        "damage_fraction": round(fraction, 6),
        "turns_to_ko": detail.turns_to_ko if detail else 0,
        "attacker_speed": int(cache.stats[attacker_row, 5]),
        "defender_speed": int(cache.stats[defender_row, 5]),
        "outspeeds": bool(cache.stats[attacker_row, 5] > cache.stats[defender_row, 5]),
    }
