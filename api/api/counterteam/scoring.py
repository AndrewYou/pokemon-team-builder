"""Counter-team scoring and selection.

Type effectiveness only. No damage formula, no stats, no moves, no speed --
those arrive in phase 9, which replaces `score` and nothing else.

Everything here runs off the in-memory derived cache. No database access, no
persistence: a request is a pure function of the enemy ids and the cache.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from api.derived.cache import DerivedCache, PokemonMeta

TEAM_SIZE = 6

# A candidate immune to everything the enemy's types can throw is strictly
# better off than one merely resisting at 0.25x, so it sits one step further up
# the same scale. A literal 1/0 would be infinity, which is neither comparable
# nor JSON-serialisable.
IMMUNE_DEFENSE = 8.0


@dataclass(frozen=True, slots=True)
class Matchup:
    """One candidate measured against one enemy."""

    score: float
    offense: float
    defense_taken: float

    @property
    def rationale_suffix(self) -> str:
        return f"takes {self.defense_taken:g}x back"


def score(
    cache: DerivedCache,
    candidate_row: int,
    enemy_row: int,
) -> Matchup:
    """Score one candidate against one enemy.

    THE function phase 9 replaces. Everything above it -- selection, coverage,
    the response shape -- is written against this signature so the damage model
    can drop in without touching them.

        offense = best multiplier the candidate's own types land on the enemy
        defense = 1 / worst multiplier the enemy's types land on the candidate
        score   = offense * defense

    Reading the candidate's types as *attacking* types is the type-only stand-in
    for "has a move that hits hard": with no movepool in scope, a Pokemon's own
    types are the best available proxy for what it can threaten.
    """
    enemy_vector = cache.vectors[enemy_row]
    candidate_vector = cache.vectors[candidate_row]

    candidate_types = cache.meta[candidate_row].types
    enemy_types = cache.meta[enemy_row].types

    offense = max(enemy_vector[cache.type_index[t]] for t in candidate_types)
    taken = max(candidate_vector[cache.type_index[t]] for t in enemy_types)

    defense = IMMUNE_DEFENSE if taken == 0.0 else 1.0 / taken
    return Matchup(
        score=float(offense * defense), offense=float(offense), defense_taken=float(taken)
    )


def score_matrix(
    cache: DerivedCache, enemy_rows: list[int]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Score every candidate against every enemy at once.

    Vectorised because selection needs the full matrix anyway: 1025 candidates
    by 6 enemies is one array operation rather than 6150 Python calls. Returns
    the scores plus the offence and taken components, which the rationales need.
    """
    type_count = cache.vectors.shape[1]

    # candidate_type_mask[c, t] is True where candidate c has type t, so the
    # offensive lookup becomes a masked max over the enemy's defensive vector.
    candidate_type_mask = np.zeros((len(cache.meta), type_count), dtype=bool)
    for row, meta in enumerate(cache.meta):
        for type_name in meta.types:
            candidate_type_mask[row, cache.type_index[type_name]] = True

    offense = np.zeros((len(cache.meta), len(enemy_rows)), dtype=np.float64)
    taken = np.zeros_like(offense)

    for column, enemy_row in enumerate(enemy_rows):
        enemy_vector = cache.vectors[enemy_row]
        # Absent types contribute 0, which never wins a max over non-negative
        # multipliers unless every present type is also 0 -- which is the
        # correct answer in that case.
        offense[:, column] = np.max(
            np.where(candidate_type_mask, enemy_vector[np.newaxis, :], 0.0), axis=1
        )
        enemy_type_columns = [cache.type_index[t] for t in cache.meta[enemy_row].types]
        taken[:, column] = np.max(cache.vectors[:, enemy_type_columns], axis=1)

    defense = np.where(taken == 0.0, IMMUNE_DEFENSE, 1.0 / np.where(taken == 0.0, 1.0, taken))
    return offense * defense, offense, taken


def select_team(scores: npt.NDArray[np.float64], size: int = TEAM_SIZE) -> list[int]:
    """Pick a team by marginal gain over what is already covered.

    Each round scores every remaining candidate by how much it *improves* the
    current best answer for each enemy, summed across enemies, and takes the
    largest. Clamping each term at zero is what makes it marginal: a candidate
    that is merely adequate against an enemy already well covered contributes
    nothing for that enemy.

    Diminishing returns falls out of this structure. There is deliberately no
    decay parameter: once an enemy is answered, the gain from answering it
    again is already zero.
    """
    candidate_count, enemy_count = scores.shape
    best = np.zeros(enemy_count, dtype=np.float64)
    totals = scores.sum(axis=1)
    chosen: list[int] = []

    for _ in range(min(size, candidate_count)):
        gains = np.maximum(scores - best, 0.0).sum(axis=1)
        if chosen:
            # Never pick the same Pokemon twice.
            gains[chosen] = -np.inf
        pick = int(np.argmax(gains))

        if gains[pick] <= 0.0:
            # Every enemy is already answered as well as anything remaining can
            # manage, so marginal gain has nothing left to distinguish. The
            # caller still wants a full team of six, so fall back to raw total
            # score and take the strongest remaining Pokemon rather than
            # returning a short roster.
            remaining = totals.copy()
            if chosen:
                remaining[chosen] = -np.inf
            pick = int(np.argmax(remaining))
            if not np.isfinite(remaining[pick]):
                break

        chosen.append(pick)
        best = np.maximum(best, scores[pick])

    return chosen


def rationale(cache: DerivedCache, candidate_row: int, enemy_row: int, matchup: Matchup) -> str:
    """Explain a matchup in the terms a player would use."""
    candidate = cache.meta[candidate_row]
    enemy = cache.meta[enemy_row]

    enemy_vector = cache.vectors[enemy_row]
    best_type = max(candidate.types, key=lambda t: enemy_vector[cache.type_index[t]])
    enemy_typing = "/".join(enemy.types)

    if matchup.offense == 0.0:
        lead = f"{candidate.name} cannot touch {enemy_typing} with its own types"
    else:
        lead = f"{best_type} hits {enemy_typing} for {matchup.offense:g}x"

    if matchup.defense_taken == 0.0:
        return f"{lead}; immune to {enemy_typing}"
    return f"{lead}; {matchup.rationale_suffix}"


def meta_of(cache: DerivedCache, row: int) -> PokemonMeta:
    return cache.meta[row]
