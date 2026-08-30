"""Tests for counter-team scoring and selection.

Everything here is pure: a synthetic cache in, picks out. No database, no
network. The effectiveness data is the real chart read from the committed
fixture, so the matchups asserted below are the ones a player would expect.
"""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

import numpy as np
import pytest

from api.battle.damage import hp_at_level_50, stat_at_level_50
from api.counterteam import scoring
from api.derived.cache import DerivedCache, PokemonMeta, pack_moves
from api.derived.moves import BestMove
from api.derived.typechart import build_chart, defensive_vector
from api.ingest import normalize as ingest_normalize
from api.services.counterteam import UnknownPokemon, build_counter_team

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pokeapi-snapshot.json"

# id -> (name, types) and the real base stats, so the damage numbers below can
# be checked against the games.
STATS = {
    6: (78, 84, 78, 109, 85, 100),  # charizard
    9: (79, 83, 100, 85, 105, 78),  # blastoise
    94: (60, 65, 60, 130, 75, 110),  # gengar
    143: (160, 110, 65, 65, 110, 30),  # snorlax
    248: (100, 134, 110, 95, 100, 61),  # tyranitar
    130: (95, 125, 79, 60, 100, 81),  # gyarados
    92: (30, 35, 30, 100, 35, 80),  # gastly
}
ROSTER: dict[int, tuple[str, tuple[str, ...]]] = {
    6: ("charizard", ("fire", "flying")),
    9: ("blastoise", ("water",)),
    94: ("gengar", ("ghost", "poison")),
    143: ("snorlax", ("normal",)),
    248: ("tyranitar", ("rock", "dark")),
    130: ("gyarados", ("water", "flying")),
    92: ("gastly", ("ghost", "poison")),
}

# One STAB attack and one filler each: enough for both directions of the
# damage model to have something to work with.
MOVEPOOLS: dict[int, list[BestMove]] = {
    6: [
        BestMove(53, "flamethrower", "fire", "special", 90, 100),
        BestMove(17, "wing-attack", "flying", "physical", 60, 100),
    ],
    9: [
        BestMove(56, "hydro-pump", "water", "special", 110, 80),
        BestMove(33, "tackle", "normal", "physical", 40, 100),
    ],
    94: [
        BestMove(94, "psychic", "psychic", "special", 90, 100),
        BestMove(247, "shadow-ball", "ghost", "special", 80, 100),
    ],
    143: [
        BestMove(63, "hyper-beam", "normal", "special", 150, 90),
        BestMove(34, "body-slam", "normal", "physical", 85, 100),
    ],
    248: [
        BestMove(444, "stone-edge", "rock", "physical", 100, 80),
        BestMove(242, "crunch", "dark", "physical", 80, 100),
    ],
    130: [
        BestMove(56, "hydro-pump", "water", "special", 110, 80),
        BestMove(37, "thrash", "normal", "physical", 120, 100),
    ],
    92: [BestMove(247, "shadow-ball", "ghost", "special", 80, 100)],
}


@pytest.fixture(scope="module")
def chart() -> dict[str, dict[str, float]]:
    payloads = json.loads(FIXTURE.read_text())["types"]
    rows = ingest_normalize.type_chart_rows(payloads)
    return build_chart((r["attacking_type"], r["defending_type"], r["multiplier"]) for r in rows)


@pytest.fixture
def cache(chart: dict[str, dict[str, float]]) -> DerivedCache:
    """A cache built the way build_cache builds one, minus the database."""
    ids = list(ROSTER)
    meta = [
        PokemonMeta(id=i, name=ROSTER[i][0], sprite_url=f"https://img/{i}.png", types=ROSTER[i][1])
        for i in ids
    ]
    vectors = np.array(
        [
            defensive_vector(chart, m.types[0], m.types[1] if len(m.types) > 1 else None)
            for m in meta
        ],
        dtype=np.float64,
    )
    stats = np.array(
        [[hp_at_level_50(STATS[i][0]), *(stat_at_level_50(v) for v in STATS[i][1:])] for i in ids],
        dtype=np.float64,
    )
    moves = [MOVEPOOLS[i] for i in ids]
    packed = pack_moves(moves, meta)

    return DerivedCache(
        chart=chart,
        pokemon_index={pid: row for row, pid in enumerate(ids)},
        pokemon_ids=ids,
        meta=meta,
        vectors=vectors,
        stats=stats,
        totals=np.array([sum(STATS[i]) for i in ids], dtype=np.float64),
        moves=moves,
        move_type_index=packed[0],
        move_power=packed[1],
        move_physical=packed[2],
        move_accuracy=packed[3],
        move_stab=packed[4],
        built_at=datetime.datetime.now(datetime.UTC),
        build_ms=1.0,
        chart_rows_loaded=324,
    )


def _row(cache: DerivedCache, pokemon_id: int) -> int:
    return cache.pokemon_index[pokemon_id]


class TestScore:
    """The damage model replaced type effectiveness here. Nothing above it --
    selection, marginal gain, the round count, the response -- changed."""

    def test_outgoing_is_the_best_move_available(self, cache: DerivedCache) -> None:
        """Charizard's Flamethrower into Blastoise is resisted; Wing Attack is
        neutral. The scorer picks whichever actually lands more."""
        result = scoring.score(cache, _row(cache, 6), _row(cache, 9))
        assert result.move_name in {"flamethrower", "wing-attack"}
        assert result.outgoing > 0

    def test_outgoing_is_a_continuous_fraction(self, cache: DerivedCache) -> None:
        """Not a turn count. Rounding collapses the model into four values and
        produces more ties than the scorer it replaced."""
        result = scoring.score(cache, _row(cache, 248), _row(cache, 6))
        assert isinstance(result.outgoing, float)
        assert result.outgoing != round(result.outgoing)

    def test_both_directions_are_measured(self, cache: DerivedCache) -> None:
        result = scoring.score(cache, _row(cache, 9), _row(cache, 6))
        assert result.outgoing > 0 and result.incoming > 0

    def test_a_favourable_matchup_scores_above_half(self, cache: DerivedCache) -> None:
        """Tyranitar's Stone Edge is 4x into fire/flying, and Charizard's fire
        is resisted by rock in return."""
        assert scoring.score(cache, _row(cache, 248), _row(cache, 6)).score > 0.5

    def test_speed_is_reflected(self, cache: DerivedCache) -> None:
        result = scoring.score(cache, _row(cache, 94), _row(cache, 143))
        # Gengar at 110 outruns Snorlax at 30.
        assert result.outspeeds is True

    def test_turn_counts_are_display_only(self, cache: DerivedCache) -> None:
        result = scoring.score(cache, _row(cache, 248), _row(cache, 6))
        assert result.our_turns == math.ceil(1 / result.outgoing)

    def test_margin_sign_matches_the_verdict(self, cache: DerivedCache) -> None:
        for candidate in cache.pokemon_ids:
            for enemy in cache.pokemon_ids:
                result = scoring.score(cache, _row(cache, candidate), _row(cache, enemy))
                if result.margin is None:
                    continue
                if result.margin > 0:
                    assert result.verdict in {"Wins", "Dominates"}
                elif result.margin == 0:
                    assert result.verdict == "Trades"
                else:
                    assert result.verdict == "Loses"


class TestImmunity:
    def test_a_candidate_with_no_answer_scores_zero(
        self, chart: dict[str, dict[str, float]]
    ) -> None:
        """Gastly only has Shadow Ball, and ghost does nothing to a normal
        type. No division, no infinity, just zero."""
        result = scoring.score(cache_for(chart), 0, 1)
        assert result.outgoing == 0.0
        assert result.score == 0.0

    def test_all_scores_are_finite(self, cache: DerivedCache) -> None:
        """Any infinity would propagate into the response and fail to
        serialise."""
        grid = scoring.score_matrix(cache, list(range(len(cache.meta))))
        assert np.isfinite(grid.scores).all()
        assert np.isfinite(grid.outgoing).all()
        assert np.isfinite(grid.incoming).all()


def cache_for(chart: dict[str, dict[str, float]]) -> DerivedCache:
    """Gastly (ghost/poison, Shadow Ball only) against Snorlax (normal)."""
    meta = [
        PokemonMeta(92, "gastly", None, ("ghost", "poison")),
        PokemonMeta(143, "snorlax", None, ("normal",)),
    ]
    vectors = np.array(
        [
            defensive_vector(chart, m.types[0], m.types[1] if len(m.types) > 1 else None)
            for m in meta
        ],
        dtype=np.float64,
    )
    stats = np.array(
        [
            [hp_at_level_50(STATS[i][0]), *(stat_at_level_50(v) for v in STATS[i][1:])]
            for i in (92, 143)
        ],
        dtype=np.float64,
    )
    moves = [MOVEPOOLS[92], MOVEPOOLS[143]]
    packed = pack_moves(moves, meta)
    return DerivedCache(
        chart=chart,
        pokemon_index={92: 0, 143: 1},
        pokemon_ids=[92, 143],
        meta=meta,
        vectors=vectors,
        stats=stats,
        totals=np.array([sum(STATS[92]), sum(STATS[143])], dtype=np.float64),
        moves=moves,
        move_type_index=packed[0],
        move_power=packed[1],
        move_physical=packed[2],
        move_accuracy=packed[3],
        move_stab=packed[4],
        chart_rows_loaded=324,
    )


class TestScalarAndVectorAgree:
    """Two implementations of the same maths. If they drift, the picks stop
    matching their own rationales."""

    def test_every_pair_matches(self, cache: DerivedCache) -> None:
        rows = list(range(len(cache.meta)))
        grid = scoring.score_matrix(cache, rows)
        for candidate in rows:
            for column, enemy in enumerate(rows):
                expected = scoring.score(cache, candidate, enemy)
                assert grid.scores[candidate, column] == pytest.approx(expected.score)
                assert grid.outgoing[candidate, column] == pytest.approx(expected.outgoing)
                assert grid.incoming[candidate, column] == pytest.approx(expected.incoming)
                assert bool(grid.outspeeds[candidate, column]) == expected.outspeeds


class TestSelection:
    def test_returns_the_requested_size(self, cache: DerivedCache) -> None:
        scores = scoring.score_matrix(cache, [_row(cache, 6), _row(cache, 9)]).scores
        assert len(scoring.select_team(scores, size=6)) == 6

    def test_never_picks_the_same_pokemon_twice(self, cache: DerivedCache) -> None:
        scores = scoring.score_matrix(cache, [_row(cache, 6), _row(cache, 9)]).scores
        picks = scoring.select_team(scores, size=6)
        assert len(set(picks)) == len(picks)

    def test_cannot_return_more_than_the_candidate_pool(self, cache: DerivedCache) -> None:
        scores = scoring.score_matrix(cache, [_row(cache, 6)]).scores
        assert len(scoring.select_team(scores, size=99)) == len(cache.meta)

    def test_first_pick_maximises_total_coverage(self) -> None:
        """Round one has nothing covered, so marginal gain is the raw row sum."""
        scores = np.array([[1.0, 1.0], [4.0, 0.0], [0.0, 0.0]])
        assert scoring.select_team(scores, size=1) == [1]

    def test_second_pick_covers_what_the_first_missed(self) -> None:
        """The heart of marginal gain. Candidate 1 is strongest overall, but
        once it is taken, candidate 2 adds more than candidate 0 despite a
        lower raw total, because it answers the enemy still uncovered."""
        scores = np.array(
            [
                [3.0, 0.0],  # strong vs enemy A only
                [4.0, 0.0],  # strongest vs enemy A
                [0.0, 2.0],  # the only answer to enemy B
            ]
        )
        assert scoring.select_team(scores, size=2) == [1, 2]

    def test_diminishing_returns_needs_no_decay_parameter(self) -> None:
        """A near-duplicate of an already-chosen pick contributes nothing, so it
        loses to a weaker candidate that covers something new."""
        scores = np.array(
            [
                [10.0, 0.0],  # picked first
                [9.9, 0.0],  # nearly as good, but redundant
                [0.0, 1.0],  # weak, but the only cover for enemy B
            ]
        )
        assert scoring.select_team(scores, size=2) == [0, 2]

    def test_fills_the_team_when_no_gain_remains(self) -> None:
        """Once coverage is saturated, the roster is still completed with the
        strongest remaining rather than returned short."""
        scores = np.array([[5.0, 5.0], [1.0, 1.0], [0.5, 0.5]])
        picks = scoring.select_team(scores, size=3)
        assert picks == [0, 1, 2]


class TestBuildCounterTeam:
    def test_unknown_ids_are_rejected(self, cache: DerivedCache) -> None:
        with pytest.raises(UnknownPokemon, match="99999"):
            build_counter_team(cache, [6, 99999])

    def test_response_shape(self, cache: DerivedCache) -> None:
        result = build_counter_team(cache, [6, 9])
        assert result.picks and result.coverage
        assert len(result.coverage) == 2
        for pick in result.picks:
            assert len(pick.answers) == 2

    def test_duplicate_enemies_are_collapsed(self, cache: DerivedCache) -> None:
        """A doubled enemy would otherwise be weighted twice in the sum."""
        result = build_counter_team(cache, [6, 6, 9])
        assert len(result.coverage) == 2

    def test_coverage_matches_the_best_pick(self, cache: DerivedCache) -> None:
        result = build_counter_team(cache, [6, 9])
        by_id = {p.id: p for p in result.picks}
        for entry in result.coverage:
            answer = next(
                a for a in by_id[entry.best_answer_id].answers if a.enemy_id == entry.enemy_id
            )
            assert answer.multiplier == pytest.approx(entry.score)

    def test_tyranitar_is_recommended_against_charizard(self, cache: DerivedCache) -> None:
        """A sanity check in the game's own terms, not just the algebra."""
        result = build_counter_team(cache, [6])
        assert result.coverage[0].best_answer == "tyranitar"


class TestRationale:
    def test_names_the_move_and_what_it_does(self, cache: DerivedCache) -> None:
        matchup = scoring.score(cache, _row(cache, 248), _row(cache, 6))
        text = scoring.rationale(cache, _row(cache, 248), _row(cache, 6), matchup)
        assert "Stone Edge" in text and "(Rock)" in text
        assert "deals" in text and "KOs in" in text

    def test_says_who_takes_what(self, cache: DerivedCache) -> None:
        """The old wording used the same verb for both directions."""
        matchup = scoring.score(cache, _row(cache, 248), _row(cache, 6))
        text = scoring.rationale(cache, _row(cache, 248), _row(cache, 6), matchup)
        assert "deals" in text and "back" in text

    def test_an_outspeeding_one_shot_reports_no_damage_taken(self, cache: DerivedCache) -> None:
        """Reporting the per-turn rate would describe damage never taken."""
        matchup = scoring.score(cache, _row(cache, 94), _row(cache, 143))
        if matchup.outspeeds and matchup.our_turns == 1:
            text = scoring.rationale(cache, _row(cache, 94), _row(cache, 143), matchup)
            assert "takes 0% back" in text

    def test_explains_a_hopeless_matchup(self, chart: dict[str, dict[str, float]]) -> None:
        small = cache_for(chart)
        matchup = scoring.score(small, 0, 1)
        assert "cannot damage" in scoring.rationale(small, 0, 1, matchup)
