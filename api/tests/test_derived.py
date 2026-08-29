"""Tests for the derived layer.

The effectiveness maths sits underneath every later feature, so a wrong
multiplier here is invisible until a counter-team recommendation is subtly
useless. All of it is pure, so all of it is tested directly.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import numpy as np
import pytest

from api.derived.cache import DerivedCache
from api.derived.typechart import (
    LEGAL_CHART_VALUES,
    LEGAL_DEFENSIVE_VALUES,
    TYPE_INDEX,
    build_chart,
    defensive_multiplier,
    defensive_vector,
    explain,
    matchup,
)
from api.ingest.normalize import CANONICAL_TYPES
from api.schemas import TypeName

# Real relationships, enough to exercise every interesting case.
ROWS = [
    ("rock", "fire", Decimal("2")),
    ("rock", "flying", Decimal("2")),
    ("grass", "fire", Decimal("0.5")),
    ("grass", "flying", Decimal("0.5")),
    ("ground", "flying", Decimal("0")),
    ("ground", "fire", Decimal("2")),
    ("water", "fire", Decimal("2")),
    ("electric", "flying", Decimal("2")),
]


@pytest.fixture
def chart() -> dict[str, dict[str, float]]:
    return build_chart(ROWS)


class TestBuildChart:
    def test_covers_every_pairing(self, chart: dict[str, dict[str, float]]) -> None:
        """324 entries, so a lookup can never miss."""
        assert len(chart) == 18
        assert sum(len(row) for row in chart.values()) == 324

    def test_unlisted_pairings_default_to_neutral(self, chart: dict[str, dict[str, float]]) -> None:
        """PokeAPI lists only the exceptions."""
        assert chart["normal"]["water"] == 1.0

    def test_listed_pairings_are_applied(self, chart: dict[str, dict[str, float]]) -> None:
        assert chart["rock"]["fire"] == 2.0
        assert chart["ground"]["flying"] == 0.0

    def test_unknown_type_names_are_ignored(self) -> None:
        """`stellar` and `shadow` exist upstream but are not battle types."""
        built = build_chart([("stellar", "fire", Decimal("2"))])
        assert "stellar" not in built


class TestDefensiveMultiplier:
    def test_charizard_versus_rock_is_four(self, chart: dict[str, dict[str, float]]) -> None:
        """Fire/Flying, both weak to rock: 2.0 * 2.0."""
        assert defensive_multiplier(chart, "rock", "fire", "flying") == 4.0

    def test_charizard_versus_grass_is_a_quarter(self, chart: dict[str, dict[str, float]]) -> None:
        """Both halves resist grass: 0.5 * 0.5."""
        assert defensive_multiplier(chart, "grass", "fire", "flying") == 0.25

    def test_immunity_beats_a_weakness(self, chart: dict[str, dict[str, float]]) -> None:
        """Ground is 2x on fire but 0x on flying. Zero wins: a ground move does
        nothing to Charizard regardless of its other half."""
        assert defensive_multiplier(chart, "ground", "fire", "flying") == 0.0

    def test_order_of_types_does_not_matter(self, chart: dict[str, dict[str, float]]) -> None:
        assert defensive_multiplier(chart, "rock", "fire", "flying") == defensive_multiplier(
            chart, "rock", "flying", "fire"
        )

    def test_single_type_uses_one_component(self, chart: dict[str, dict[str, float]]) -> None:
        assert defensive_multiplier(chart, "rock", "fire", None) == 2.0

    def test_neutral_when_nothing_applies(self, chart: dict[str, dict[str, float]]) -> None:
        assert defensive_multiplier(chart, "normal", "fire", "flying") == 1.0


class TestDefensiveVector:
    def test_has_one_entry_per_type(self, chart: dict[str, dict[str, float]]) -> None:
        assert len(defensive_vector(chart, "fire", "flying")) == 18

    def test_is_ordered_by_canonical_types(self, chart: dict[str, dict[str, float]]) -> None:
        vector = defensive_vector(chart, "fire", "flying")
        assert vector[TYPE_INDEX["rock"]] == 4.0
        assert vector[TYPE_INDEX["ground"]] == 0.0

    def test_every_value_is_legal(self, chart: dict[str, dict[str, float]]) -> None:
        for type1 in CANONICAL_TYPES:
            for type2 in (*CANONICAL_TYPES, None):
                for value in defensive_vector(chart, type1, type2):
                    assert value in LEGAL_DEFENSIVE_VALUES, (type1, type2, value)


class TestLegalValues:
    def test_defensive_values_are_products_of_chart_values(self) -> None:
        """The six defensive values are exactly what multiplying two chart
        values can produce; 4.0 and 0.25 exist only because of dual typing."""
        products = {a * b for a in LEGAL_CHART_VALUES for b in LEGAL_CHART_VALUES}
        assert products == set(LEGAL_DEFENSIVE_VALUES)


class TestExplain:
    def test_dual_type_shows_both_components(self, chart: dict[str, dict[str, float]]) -> None:
        assert explain(chart, "rock", "fire", "flying") == "rock vs fire/flying = 2 * 2 = 4"

    def test_single_type_shows_one(self, chart: dict[str, dict[str, float]]) -> None:
        assert explain(chart, "rock", "fire", None) == "rock vs fire = 2"


class TestMatchup:
    def test_missing_attacking_type_is_neutral(self, chart: dict[str, dict[str, float]]) -> None:
        assert matchup(chart, "stellar", "fire") == 1.0


def _cache(chart: dict[str, dict[str, float]]) -> DerivedCache:
    vectors = np.array(
        [defensive_vector(chart, "fire", "flying"), defensive_vector(chart, "electric", None)],
        dtype=np.float64,
    )
    return DerivedCache(
        chart=chart,
        pokemon_index={6: 0, 25: 1},
        pokemon_ids=[6, 25],
        vectors=vectors,
        built_at=datetime.datetime.now(datetime.UTC),
        build_ms=1.0,
    )


class TestDerivedCache:
    def test_multiplier_reads_the_matrix(self, chart: dict[str, dict[str, float]]) -> None:
        assert _cache(chart).multiplier(6, "rock") == 4.0

    def test_vector_as_dict_covers_all_types(self, chart: dict[str, dict[str, float]]) -> None:
        assert len(_cache(chart).vector_as_dict(6)) == 18

    def test_unknown_pokemon_raises(self, chart: dict[str, dict[str, float]]) -> None:
        with pytest.raises(KeyError):
            _cache(chart).vector_for(9999)

    def test_unknown_attacking_type_raises(self, chart: dict[str, dict[str, float]]) -> None:
        with pytest.raises(KeyError):
            _cache(chart).multiplier(6, "stellar")

    def test_legal_matrix_reports_no_violations(self, chart: dict[str, dict[str, float]]) -> None:
        assert _cache(chart).illegal_value_count() == 0

    def test_illegal_values_are_detected(self, chart: dict[str, dict[str, float]]) -> None:
        """A 3x multiplier cannot arise from any legal pair, so it means the
        chart itself is wrong."""
        cache = _cache(chart)
        cache.vectors[0][0] = 3.0
        assert cache.illegal_value_count() == 1


class TestTypeNameEnum:
    def test_matches_canonical_types_exactly(self) -> None:
        """The enum is spelled out for type checkers; this stops it drifting."""
        assert [member.value for member in TypeName] == list(CANONICAL_TYPES)


class TestChartCompleteness:
    """An empty type_chart table still produces a full nested dict of 1.0s, so
    completeness has to be tracked separately from the dict's shape."""

    def test_fully_loaded_chart_is_complete(self, chart: dict[str, dict[str, float]]) -> None:
        cache = _cache(chart)
        cache.chart_rows_loaded = 324
        assert cache.chart_complete

    def test_empty_chart_is_not_complete(self, chart: dict[str, dict[str, float]]) -> None:
        cache = _cache(chart)
        cache.chart_rows_loaded = 0
        assert not cache.chart_complete

    def test_partial_chart_is_not_complete(self, chart: dict[str, dict[str, float]]) -> None:
        cache = _cache(chart)
        cache.chart_rows_loaded = 323
        assert not cache.chart_complete

    def test_defaulted_chart_would_answer_neutral(self) -> None:
        """The reason completeness matters: a chart built from nothing returns a
        confident 1.0 for every matchup rather than failing."""
        empty = build_chart([])
        assert defensive_multiplier(empty, "rock", "fire", "flying") == 1.0
