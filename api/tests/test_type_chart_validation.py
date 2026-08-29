"""Tests for the type chart's self-check.

A chart that is merely plausible is the worst possible outcome: every damage
number downstream is wrong, and no test of the *consuming* code would notice.
The two realistic ways to build a plausible-but-wrong chart are reading
past_damage_relations and failing to filter non-battle types, so both get a
test, plus one that validates the real committed fixture.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from api.ingest import normalize
from api.ingest.normalize import (
    CANONICAL_TYPES,
    EXPECTED_MULTIPLIER_DISTRIBUTION,
    TypeChartValidationError,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pokeapi-snapshot.json"


def _relations(**kwargs: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    base: dict[str, list[dict[str, str]]] = {
        "double_damage_to": [],
        "half_damage_to": [],
        "no_damage_to": [],
    }
    base.update(kwargs)
    return base


def _payloads(**overrides: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    return [
        {"id": i, "name": name, "damage_relations": overrides.get(name, _relations())}
        for i, name in enumerate(CANONICAL_TYPES, start=1)
    ]


@pytest.fixture(scope="module")
def type_payloads() -> list[dict[str, Any]]:
    """The real committed snapshot."""
    return list(json.loads(FIXTURE.read_text())["types"])


class TestRealFixture:
    """The strongest guard available: the data actually committed to the repo."""

    def test_fixture_still_carries_extra_non_battle_types(
        self, type_payloads: list[dict[str, Any]]
    ) -> None:
        """21 entries upstream, not 18 and not 20: unknown, shadow, and the
        Gen 9 addition stellar. A filter naming only the first two lets stellar
        through and produces 361 rows."""
        names = {p["name"] for p in type_payloads}
        assert {"unknown", "shadow", "stellar"} <= names
        assert len(type_payloads) == 21

    def test_produces_exactly_the_known_chart(self, type_payloads: list[dict[str, Any]]) -> None:
        rows = normalize.type_chart_rows(type_payloads)
        assert normalize.validate_type_chart(rows) == EXPECTED_MULTIPLIER_DISTRIBUTION

    def test_distribution_sums_to_324(self) -> None:
        assert sum(EXPECTED_MULTIPLIER_DISTRIBUTION.values()) == 324

    def test_fixture_does_not_carry_past_damage_relations(
        self, type_payloads: list[dict[str, Any]]
    ) -> None:
        """Dropped at trim time so it cannot be read by accident."""
        assert not any("past_damage_relations" in p for p in type_payloads)


class TestPastDamageRelationsIsIgnored:
    """Gen 1 had bug 2x into poison, ice 1x into fire, ghost 0x into psychic.
    Reading the superseded chart yields a plausible chart that disagrees with
    pokemondb.net/type."""

    @pytest.fixture
    def misleading(self) -> list[dict[str, Any]]:
        payloads = _payloads(
            bug=_relations(half_damage_to=[{"name": "poison"}]),
            ghost=_relations(double_damage_to=[{"name": "psychic"}]),
        )
        for payload in payloads:
            # The trap: superseded data sitting right next to the real thing.
            payload["past_damage_relations"] = [
                {
                    "generation": {"name": "generation-i"},
                    "damage_relations": _relations(
                        double_damage_to=[{"name": "poison"}],
                        no_damage_to=[{"name": "psychic"}],
                    ),
                }
            ]
        return payloads

    def test_modern_bug_into_poison_is_used(self, misleading: list[dict[str, Any]]) -> None:
        chart = {
            (r["attacking_type"], r["defending_type"]): r["multiplier"]
            for r in normalize.type_chart_rows(misleading)
        }
        assert chart[("bug", "poison")] == Decimal("0.5")

    def test_modern_ghost_into_psychic_is_used(self, misleading: list[dict[str, Any]]) -> None:
        chart = {
            (r["attacking_type"], r["defending_type"]): r["multiplier"]
            for r in normalize.type_chart_rows(misleading)
        }
        assert chart[("ghost", "psychic")] == Decimal("2")


class TestNonBattleTypesAreFiltered:
    def test_extra_types_do_not_inflate_the_row_count(self) -> None:
        """18 real + unknown + shadow + stellar would be 21 x 21 = 441."""
        payloads = _payloads()
        for name, type_id in (("unknown", 10001), ("shadow", 10002), ("stellar", 19)):
            payloads.append({"id": type_id, "name": name, "damage_relations": _relations()})
        assert len(normalize.type_chart_rows(payloads)) == 324

    def test_a_missing_real_type_fails_loudly(self) -> None:
        payloads = [p for p in _payloads() if p["name"] != "fairy"]
        with pytest.raises(TypeChartValidationError, match="fairy"):
            normalize.type_chart_rows(payloads)


class TestValidation:
    def test_rejects_a_short_chart(self) -> None:
        rows = normalize.type_chart_rows(_payloads())[:323]
        with pytest.raises(TypeChartValidationError, match="expected 324 rows"):
            normalize.validate_type_chart(rows)

    def test_rejects_a_wrong_distribution(self) -> None:
        """An all-neutral chart is exactly 324 rows and completely wrong."""
        rows = normalize.type_chart_rows(_payloads())
        with pytest.raises(TypeChartValidationError, match="past_damage_relations"):
            normalize.validate_type_chart(rows)

    def test_error_names_the_likely_cause(self) -> None:
        rows = normalize.type_chart_rows(_payloads())
        with pytest.raises(TypeChartValidationError) as exc:
            normalize.validate_type_chart(rows)
        assert "{'1': 324}" in str(exc.value)


class TestFormatting:
    @pytest.mark.parametrize(
        ("value", "expected"), [(0.0, "0"), (0.5, "0.5"), (1.0, "1"), (2.0, "2")]
    )
    def test_multiplier_keys_are_stable(self, value: float, expected: str) -> None:
        assert normalize.format_multiplier(value) == expected


class TestAllowlist:
    """The 18 battle types are allowlisted, not the extras blocklisted.

    A blocklist breaks silently the moment PokeAPI adds an entry: 19 types
    writes 361 rows and 20 writes 400, and neither looks obviously wrong.
    """

    EXPECTED = frozenset(
        {
            "normal",
            "fire",
            "water",
            "electric",
            "grass",
            "ice",
            "fighting",
            "poison",
            "ground",
            "flying",
            "psychic",
            "bug",
            "rock",
            "ghost",
            "dragon",
            "dark",
            "steel",
            "fairy",
        }
    )

    def test_allowlist_is_a_frozenset(self) -> None:
        assert isinstance(normalize.CANONICAL_TYPE_SET, frozenset)

    def test_allowlist_contains_exactly_the_18_battle_types(self) -> None:
        assert normalize.CANONICAL_TYPE_SET == self.EXPECTED

    def test_there_are_exactly_18(self) -> None:
        """Asserted at import too, so a typo fails at startup rather than
        producing a chart that is quietly the wrong size."""
        assert len(normalize.CANONICAL_TYPES) == 18
        assert len(normalize.CANONICAL_TYPE_SET) == 18

    def test_tuple_and_set_agree(self) -> None:
        assert set(normalize.CANONICAL_TYPES) == normalize.CANONICAL_TYPE_SET

    def test_a_type_added_tomorrow_needs_no_code_change(self) -> None:
        """The real property an allowlist buys: an entry nobody has heard of is
        excluded without anyone editing a blocklist."""
        payloads = _payloads()
        payloads.append({"id": 20, "name": "quantum", "damage_relations": _relations()})
        rows = normalize.type_chart_rows(payloads)
        assert len(rows) == 324
        assert "quantum" not in {r["attacking_type"] for r in rows}


class TestVectorColumnOrder:
    """CANONICAL_TYPES is ordered because it defines the numpy column layout."""

    def test_order_is_pokeapi_type_ids_1_to_18(self, type_payloads: list[dict[str, Any]]) -> None:
        """Not an arbitrary order: it matches the upstream ids, so a column can
        be traced back to a real resource."""
        by_id = sorted((p for p in type_payloads if p["id"] <= 18), key=lambda p: p["id"])
        assert tuple(p["name"] for p in by_id) == normalize.CANONICAL_TYPES

    def test_type_index_is_built_from_the_ordered_tuple(self) -> None:
        """If this were built from the frozenset, hash randomisation would give
        each process a different column layout for the same data."""
        from api.derived.typechart import TYPE_INDEX

        assert list(TYPE_INDEX) == list(normalize.CANONICAL_TYPES)
        assert TYPE_INDEX[normalize.CANONICAL_TYPES[0]] == 0
        assert TYPE_INDEX[normalize.CANONICAL_TYPES[17]] == 17


class TestStellarExclusion:
    """Stellar is excluded on semantics, not convenience."""

    def test_no_species_has_stellar_as_a_type(self) -> None:
        """The justification, checked against the real snapshot: stellar is a
        Terastal mechanic, so it never appears as type1 or type2 and has no
        meaningful row in a defensive chart."""
        snapshot = json.loads(FIXTURE.read_text())
        used = {
            entry["type"]["name"] for pokemon in snapshot["pokemon"] for entry in pokemon["types"]
        }
        assert "stellar" not in used
        assert used <= normalize.CANONICAL_TYPE_SET

    def test_stellar_is_present_upstream_but_excluded(
        self, type_payloads: list[dict[str, Any]]
    ) -> None:
        assert "stellar" in {p["name"] for p in type_payloads}
        assert "stellar" not in normalize.CANONICAL_TYPE_SET
