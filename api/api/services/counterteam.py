"""Assemble a counter-team response from the derived cache."""

from __future__ import annotations

import numpy as np

from api.counterteam import scoring
from api.derived.cache import DerivedCache
from api.schemas import (
    CounterAnswer,
    CounterPick,
    CounterTeamResponse,
    CoverageEntry,
)


class UnknownPokemon(ValueError):
    """One or more requested ids are not in the derived cache."""


def build_counter_team(cache: DerivedCache, enemy_ids: list[int]) -> CounterTeamResponse:
    """Recommend a team answering the given enemies.

    Stateless: nothing is written, nothing is read from the database. The whole
    computation is a function of the enemy ids and the in-memory cache.
    """
    unknown = [pid for pid in enemy_ids if pid not in cache.pokemon_index]
    if unknown:
        raise UnknownPokemon(f"Unknown Pokemon ids: {unknown}.")

    # Deduplicated while preserving order: a doubled enemy would otherwise be
    # weighted twice in the marginal-gain sum.
    seen: dict[int, None] = dict.fromkeys(enemy_ids)
    enemies = list(seen)
    enemy_rows = [cache.pokemon_index[pid] for pid in enemies]

    grid = scoring.score_matrix(cache, enemy_rows)
    scores = grid.scores
    chosen_rows = scoring.select_team(
        scores,
        size=len(enemy_rows),
        type_mask=scoring.candidate_type_mask(cache),
        stat_totals=cache.totals,
        ids=np.array(cache.pokemon_ids, dtype=np.int64),
    )

    picks: list[CounterPick] = []
    for row in chosen_rows:
        meta = cache.meta[row]
        answers = []
        for column, enemy_row in enumerate(enemy_rows):
            moves = cache.moves[row]
            outgoing = float(grid.outgoing[row, column])
            chosen_move = (
                moves[int(grid.move_index[row, column])] if moves and outgoing > 0 else None
            )
            matchup = scoring.Matchup(
                score=float(scores[row, column]),
                outgoing=outgoing,
                incoming=float(grid.incoming[row, column]),
                move_name=chosen_move.name if chosen_move else "",
                move_type=chosen_move.type if chosen_move else "",
                damage_class=chosen_move.damage_class if chosen_move else "",
                outspeeds=bool(grid.outspeeds[row, column]),
            )
            answers.append(
                CounterAnswer(
                    enemy_id=cache.meta[enemy_row].id,
                    enemy_name=cache.meta[enemy_row].name,
                    multiplier=round(matchup.score, 4),
                    rationale=scoring.rationale(cache, row, enemy_row, matchup),
                    move_name=matchup.move_name,
                    damage_class=matchup.damage_class,
                    damage_fraction=round(matchup.outgoing, 4),
                    turns_to_ko=matchup.turns_to_ko,
                    outspeeds=matchup.outspeeds,
                )
            )
        picks.append(
            CounterPick(
                id=meta.id,
                name=meta.name,
                sprite_url=meta.sprite_url,
                types=list(meta.types),
                answers=answers,
            )
        )

    coverage: list[CoverageEntry] = []
    for column, enemy_row in enumerate(enemy_rows):
        enemy_meta = cache.meta[enemy_row]
        best_row = max(chosen_rows, key=lambda r: scores[r, column]) if chosen_rows else None
        if best_row is None:
            continue
        coverage.append(
            CoverageEntry(
                enemy_id=enemy_meta.id,
                enemy_name=enemy_meta.name,
                best_answer=cache.meta[best_row].name,
                best_answer_id=cache.meta[best_row].id,
                score=round(float(scores[best_row, column]), 4),
            )
        )

    # Echoed so the frontend can assert the count rather than assume it.
    return CounterTeamResponse(size=len(picks), picks=picks, coverage=coverage)
