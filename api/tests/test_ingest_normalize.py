"""Tests for the pure ingest transforms.

These are the functions change detection depends on, so hash stability gets
more attention than the row mapping does.
"""

from decimal import Decimal
from typing import Any

import pytest

from api.ingest import normalize


def test_id_from_url_handles_trailing_slash() -> None:
    assert normalize.id_from_url("https://pokeapi.co/api/v2/move/33/") == 33
    assert normalize.id_from_url("https://pokeapi.co/api/v2/move/33") == 33


def test_digest_is_stable_across_key_order() -> None:
    """Canonicalisation is the whole point: equal data must hash equal."""
    assert normalize.digest({"a": 1, "b": 2}) == normalize.digest({"b": 2, "a": 1})


def test_digest_distinguishes_different_data() -> None:
    assert normalize.digest({"a": 1}) != normalize.digest({"a": 2})


class TestTrim:
    def test_drops_version_group_details(self, bulbasaur: dict[str, Any]) -> None:
        """This is ~90% of a real payload; keeping it makes the fixture unshippable."""
        trimmed = normalize.trim_pokemon(bulbasaur)
        assert all("version_group_details" not in entry for entry in trimmed["moves"])

    def test_drops_bulk_sections_but_keeps_what_we_read(self, bulbasaur: dict[str, Any]) -> None:
        trimmed = normalize.trim_pokemon(bulbasaur)
        for dropped in ("game_indices", "held_items", "cries"):
            assert dropped not in trimmed
        for kept in ("id", "name", "types", "stats", "abilities", "moves", "is_default"):
            assert kept in trimmed
        assert trimmed["sprites"] == {"front_default": "https://img/1.png"}

    def test_is_idempotent(self, bulbasaur: dict[str, Any]) -> None:
        """The fixture stores trimmed payloads and is trimmed again on load."""
        once = normalize.trim_pokemon(bulbasaur)
        assert normalize.trim_pokemon(once) == once

    def test_row_from_trimmed_payload_matches_row_from_full(
        self, bulbasaur: dict[str, Any]
    ) -> None:
        """Seeding from the fixture must produce exactly what a live seed would."""
        assert normalize.pokemon_row(normalize.trim_pokemon(bulbasaur)) == normalize.pokemon_row(
            bulbasaur
        )


class TestPokemonRow:
    def test_maps_stats_and_types_by_slot(self, bulbasaur: dict[str, Any]) -> None:
        row = normalize.pokemon_row(bulbasaur)
        assert (row["type1"], row["type2"]) == ("grass", "poison")
        assert row["base_hp"] == 45
        assert row["base_spatk"] == 65

    def test_single_type_leaves_type2_null(self, bulbasaur: dict[str, Any]) -> None:
        bulbasaur["types"] = [{"slot": 1, "type": {"name": "grass"}}]
        assert normalize.pokemon_row(bulbasaur)["type2"] is None

    def test_stats_are_stored_unconverted(self, bulbasaur: dict[str, Any]) -> None:
        """Base stats, never level-50 values: a converted write makes every
        subsequent sync diff report a change that did not happen."""
        assert normalize.pokemon_row(bulbasaur)["base_hp"] == 45

    def test_missing_sprite_is_tolerated(self, bulbasaur: dict[str, Any]) -> None:
        bulbasaur["sprites"] = {"front_default": None}
        assert normalize.pokemon_row(bulbasaur)["sprite_url"] is None


class TestHashes:
    def test_stats_hash_changes_when_a_stat_changes(self, bulbasaur: dict[str, Any]) -> None:
        before = normalize.stats_hash(bulbasaur)
        bulbasaur["stats"][0]["base_stat"] = 46
        assert normalize.stats_hash(bulbasaur) != before

    def test_stats_hash_ignores_unrelated_edits(self, bulbasaur: dict[str, Any]) -> None:
        before = normalize.stats_hash(bulbasaur)
        bulbasaur["weight"] = 999
        assert normalize.stats_hash(bulbasaur) == before

    def test_moves_hash_ignores_ordering(self, bulbasaur: dict[str, Any]) -> None:
        before = normalize.moves_hash(bulbasaur)
        bulbasaur["moves"].reverse()
        assert normalize.moves_hash(bulbasaur) == before

    def test_moves_hash_changes_when_a_move_is_removed(self, bulbasaur: dict[str, Any]) -> None:
        before = normalize.moves_hash(bulbasaur)
        bulbasaur["moves"].pop()
        assert normalize.moves_hash(bulbasaur) != before

    def test_types_hash_respects_slot_order(self, bulbasaur: dict[str, Any]) -> None:
        """grass/poison and poison/grass are genuinely different Pokemon."""
        before = normalize.types_hash(bulbasaur)
        bulbasaur["types"] = [
            {"slot": 1, "type": {"name": "poison"}},
            {"slot": 2, "type": {"name": "grass"}},
        ]
        assert normalize.types_hash(bulbasaur) != before

    def test_sprite_hash_tracks_the_url(self, bulbasaur: dict[str, Any]) -> None:
        before = normalize.sprite_hash(bulbasaur)
        bulbasaur["sprites"]["front_default"] = "https://img/1-v2.png"
        assert normalize.sprite_hash(bulbasaur) != before


class TestMoveRow:
    def test_maps_nested_names(self, tackle: dict[str, Any]) -> None:
        row = normalize.move_row(tackle)
        assert row["type"] == "normal"
        assert row["damage_class"] == "physical"

    def test_status_move_keeps_null_power(self, tackle: dict[str, Any]) -> None:
        tackle["power"] = None
        assert normalize.move_row(tackle)["power"] is None

    def test_content_hash_changes_with_power(self, tackle: dict[str, Any]) -> None:
        before = normalize.move_content_hash(tackle)
        tackle["power"] = 50
        assert normalize.move_content_hash(tackle) != before


class TestRelations:
    def test_pokemon_move_rows_drop_unknown_moves(self, bulbasaur: dict[str, Any]) -> None:
        """A move absent from the move table would violate the foreign key."""
        rows = normalize.pokemon_move_rows(bulbasaur, known_move_ids={33})
        assert rows == [{"pokemon_id": 1, "move_id": 33}]

    def test_abilities_are_deduplicated(self, bulbasaur: dict[str, Any]) -> None:
        bulbasaur["abilities"].append({"ability": {"name": "overgrow"}, "is_hidden": False})
        rows = normalize.pokemon_ability_rows(bulbasaur)
        assert len(rows) == 2
        assert {r["ability_name"] for r in rows} == {"overgrow", "chlorophyll"}

    def test_hidden_ability_flag_is_preserved(self, bulbasaur: dict[str, Any]) -> None:
        rows = {
            r["ability_name"]: r["is_hidden"] for r in normalize.pokemon_ability_rows(bulbasaur)
        }
        assert rows == {"overgrow": False, "chlorophyll": True}


class TestTypeChart:
    @pytest.fixture
    def type_payloads(self) -> list[dict[str, Any]]:
        """Every canonical type, with only fire's real relations filled in."""
        payloads: list[dict[str, Any]] = []
        for index, name in enumerate(normalize.CANONICAL_TYPES, start=1):
            relations: dict[str, list[dict[str, str]]] = {
                "double_damage_to": [],
                "half_damage_to": [],
                "no_damage_to": [],
            }
            if name == "fire":
                relations["double_damage_to"] = [{"name": "grass"}, {"name": "ice"}]
                relations["half_damage_to"] = [{"name": "water"}, {"name": "dragon"}]
            if name == "normal":
                relations["no_damage_to"] = [{"name": "ghost"}]
            payloads.append({"id": index, "name": name, "damage_relations": relations})
        # PokeAPI also serves these; they must not reach the chart.
        payloads.append({"id": 99, "name": "stellar", "damage_relations": relations})
        payloads.append({"id": 100, "name": "unknown", "damage_relations": relations})
        return payloads

    def test_chart_is_exactly_324_rows(self, type_payloads: list[dict[str, Any]]) -> None:
        assert len(normalize.type_chart_rows(type_payloads)) == 324

    def test_non_battle_types_are_excluded(self, type_payloads: list[dict[str, Any]]) -> None:
        rows = normalize.type_chart_rows(type_payloads)
        names = {r["attacking_type"] for r in rows} | {r["defending_type"] for r in rows}
        assert "stellar" not in names
        assert "unknown" not in names

    def test_multipliers(self, type_payloads: list[dict[str, Any]]) -> None:
        chart = {
            (r["attacking_type"], r["defending_type"]): r["multiplier"]
            for r in normalize.type_chart_rows(type_payloads)
        }
        assert chart[("fire", "grass")] == Decimal("2")
        assert chart[("fire", "water")] == Decimal("0.5")
        assert chart[("normal", "ghost")] == Decimal("0")
        # Everything unstated defaults to neutral, so no lookup can miss.
        assert chart[("fire", "fire")] == Decimal("1")
        assert chart[("water", "grass")] == Decimal("1")
