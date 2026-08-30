"""Tests for counter-team scoring and selection.

Everything here is pure: a synthetic cache in, picks out. No database, no
network. The effectiveness data is the real chart read from the committed
fixture, so the matchups asserted below are the ones a player would expect.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np
import pytest

from api.counterteam import scoring
from api.derived.cache import DerivedCache, PokemonMeta
from api.derived.typechart import build_chart, defensive_vector
from api.ingest import normalize as ingest_normalize
from api.services.counterteam import UnknownPokemon, build_counter_team

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pokeapi-snapshot.json"

# id -> (name, types). Chosen to cover the interesting cases: a doubly-weak
# dual type, an immunity, and a mono type.
ROSTER: dict[int, tuple[str, tuple[str, ...]]] = {
    6: ("charizard", ("fire", "flying")),
    9: ("blastoise", ("water",)),
    94: ("gengar", ("ghost", "poison")),
    143: ("snorlax", ("normal",)),
    248: ("tyranitar", ("rock", "dark")),
    130: ("gyarados", ("water", "flying")),
    92: ("gastly", ("ghost", "poison")),
}


@pytest.fixture(scope="module")
def chart() -> dict[str, dict[str, float]]:
    payloads = json.loads(FIXTURE.read_text())["types"]
    rows = ingest_normalize.type_chart_rows(payloads)
    return build_chart((r["attacking_type"], r["defending_type"], r["multiplier"]) for r in rows)


@pytest.fixture
def cache(chart: dict[str, dict[str, float]]) -> DerivedCache:
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
    return DerivedCache(
        chart=chart,
        pokemon_index={pid: row for row, pid in enumerate(ids)},
        pokemon_ids=ids,
        meta=meta,
        vectors=vectors,
        built_at=datetime.datetime.now(datetime.UTC),
        build_ms=1.0,
        chart_rows_loaded=324,
    )


def _row(cache: DerivedCache, pokemon_id: int) -> int:
    return cache.pokemon_index[pokemon_id]


class TestScore:
    def test_tyranitar_answers_charizard(self, cache: DerivedCache) -> None:
        """Rock hits fire/flying for 4x; charizard's fire and flying hit
        rock/dark for 0.5x. 4 / 0.5 = 8."""
        result = scoring.score(cache, _row(cache, 248), _row(cache, 6))
        assert result.offense == 4.0
        assert result.defense_taken == 0.5
        assert result.score == 8.0

    def test_offense_is_the_best_of_the_candidate_types(self, cache: DerivedCache) -> None:
        """Tyranitar is rock/dark; rock is 4x into fire/flying and dark is 1x,
        so the better of the two is used."""
        result = scoring.score(cache, _row(cache, 248), _row(cache, 6))
        assert result.offense == 4.0

    def test_defense_is_the_worst_the_enemy_lands(self, cache: DerivedCache) -> None:
        """Gengar attacks with ghost and poison. Against snorlax (normal),
        ghost is 0x but poison is 1x, and the worst case is what matters."""
        result = scoring.score(cache, _row(cache, 143), _row(cache, 94))
        assert result.defense_taken == 1.0

    def test_zero_offense_scores_zero(self, cache: DerivedCache) -> None:
        """Snorlax is normal, and normal cannot touch a ghost at all."""
        result = scoring.score(cache, _row(cache, 143), _row(cache, 94))
        assert result.offense == 0.0
        assert result.score == 0.0


class TestImmunity:
    def test_immunity_does_not_divide_by_zero(self, cache: DerivedCache) -> None:
        """Gengar is ghost/poison and snorlax is normal, so neither of gengar's
        types touches it... but the reverse case is the one that matters: a
        candidate immune to everything the enemy has would be 1/0."""
        result = scoring.score(cache, _row(cache, 94), _row(cache, 143))
        assert np.isfinite(result.score)

    def test_immune_candidate_gets_the_capped_defence(
        self, chart: dict[str, dict[str, float]]
    ) -> None:
        """A normal-type enemy against a ghost candidate: normal does 0x to
        ghost, so the candidate takes nothing and defence is capped rather than
        infinite, which is neither comparable nor JSON-serialisable."""
        meta = [
            PokemonMeta(1, "snorlax", None, ("normal",)),
            PokemonMeta(2, "gengar", None, ("ghost", "poison")),
        ]
        vectors = np.array(
            [
                defensive_vector(chart, m.types[0], m.types[1] if len(m.types) > 1 else None)
                for m in meta
            ],
            dtype=np.float64,
        )
        cache = DerivedCache(
            chart=chart,
            pokemon_index={1: 0, 2: 1},
            pokemon_ids=[1, 2],
            meta=meta,
            vectors=vectors,
            built_at=datetime.datetime.now(datetime.UTC),
            build_ms=1.0,
            chart_rows_loaded=324,
        )
        result = scoring.score(cache, 1, 0)
        assert result.defense_taken == 0.0
        assert result.score == scoring.IMMUNE_DEFENSE * result.offense

    def test_all_scores_are_finite(self, cache: DerivedCache) -> None:
        """Any infinity would propagate into the response and fail to serialise."""
        scores, _, _ = scoring.score_matrix(cache, list(range(len(cache.meta))))
        assert np.isfinite(scores).all()


class TestScalarAndVectorAgree:
    """Two implementations of the same maths. If they drift, the picks stop
    matching their own rationales."""

    def test_every_pair_matches(self, cache: DerivedCache) -> None:
        enemy_rows = list(range(len(cache.meta)))
        scores, offense, taken = scoring.score_matrix(cache, enemy_rows)
        for candidate_row in range(len(cache.meta)):
            for column, enemy_row in enumerate(enemy_rows):
                expected = scoring.score(cache, candidate_row, enemy_row)
                assert scores[candidate_row, column] == pytest.approx(expected.score)
                assert offense[candidate_row, column] == pytest.approx(expected.offense)
                assert taken[candidate_row, column] == pytest.approx(expected.defense_taken)


class TestSelection:
    def test_returns_the_requested_size(self, cache: DerivedCache) -> None:
        scores, _, _ = scoring.score_matrix(cache, [_row(cache, 6), _row(cache, 9)])
        assert len(scoring.select_team(scores, size=6)) == 6

    def test_never_picks_the_same_pokemon_twice(self, cache: DerivedCache) -> None:
        scores, _, _ = scoring.score_matrix(cache, [_row(cache, 6), _row(cache, 9)])
        picks = scoring.select_team(scores, size=6)
        assert len(set(picks)) == len(picks)

    def test_cannot_return_more_than_the_candidate_pool(self, cache: DerivedCache) -> None:
        scores, _, _ = scoring.score_matrix(cache, [_row(cache, 6)])
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
    def test_names_the_effective_type(self, cache: DerivedCache) -> None:
        matchup = scoring.score(cache, _row(cache, 248), _row(cache, 6))
        text = scoring.rationale(cache, _row(cache, 248), _row(cache, 6), matchup)
        assert "rock hits fire/flying for 4x" in text

    def test_explains_a_hopeless_matchup(self, cache: DerivedCache) -> None:
        matchup = scoring.score(cache, _row(cache, 143), _row(cache, 94))
        text = scoring.rationale(cache, _row(cache, 143), _row(cache, 94), matchup)
        assert "cannot touch" in text


class TestEqualSize:
    """The counter team matches the team it answers. The count is derived from
    the request rather than configured, so there is no way to ask for a
    mismatch."""

    @pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
    def test_picks_match_the_enemy_count(self, cache: DerivedCache, count: int) -> None:
        enemies = list(ROSTER)[:count]
        result = build_counter_team(cache, enemies)
        assert result.size == len(result.picks) == count

    @pytest.mark.parametrize("count", [1, 2, 3])
    def test_coverage_has_one_entry_per_enemy(self, cache: DerivedCache, count: int) -> None:
        enemies = list(ROSTER)[:count]
        assert len(build_counter_team(cache, enemies).coverage) == count

    def test_every_pick_answers_every_enemy(self, cache: DerivedCache) -> None:
        result = build_counter_team(cache, [6, 9, 94])
        assert all(len(pick.answers) == 3 for pick in result.picks)

    def test_size_field_matches_the_picks(self, cache: DerivedCache) -> None:
        """Echoed so the frontend can assert rather than assume."""
        result = build_counter_team(cache, [6, 9])
        assert result.size == len(result.picks)

    def test_select_team_requires_a_size(self) -> None:
        """A default is what made every request return six picks: the caller
        never passed one, so nothing looked wrong at the call site."""
        import inspect

        signature = inspect.signature(scoring.select_team)
        assert signature.parameters["size"].default is inspect.Parameter.empty


class TestDiversity:
    """Against several Pokemon of one type, one good answer covers them all and
    every remaining candidate has zero marginal gain. Ranking those by raw score
    returns near-identical Pokemon, which is a fragile team and useless advice."""

    def test_saturated_rounds_prefer_unrepresented_types(self) -> None:
        # Two candidates answer identically; the third is weaker but new.
        scores = np.array([[8.0], [8.0], [8.0]])
        mask = np.array(
            [
                [True, False, False],  # picked first
                [True, False, False],  # same typing, nothing new
                [False, True, False],  # a type the team lacks
            ]
        )
        assert scoring.select_team(scores, size=2, type_mask=mask) == [0, 2]

    def test_without_a_mask_the_ranking_is_unchanged(self) -> None:
        """Diversity is a tie-break, not a change to the scoring."""
        scores = np.array([[8.0], [8.0], [1.0]])
        assert scoring.select_team(scores, size=2) == [0, 1]

    def test_marginal_gain_still_wins_over_breadth(self) -> None:
        """Covering an uncovered enemy beats broadening the typing."""
        scores = np.array([[4.0, 0.0], [0.0, 4.0], [0.0, 0.0]])
        mask = np.array([[True, False, False], [True, False, False], [False, True, True]])
        # Candidate 1 shares a typing with 0 but answers the second enemy.
        assert scoring.select_team(scores, size=2, type_mask=mask) == [0, 1]
