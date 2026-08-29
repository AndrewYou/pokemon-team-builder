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
