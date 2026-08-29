"""Tests for the projection and the diff.

These are the deliverable for this phase. The failure mode being defended
against is not a crash but a false positive: a change feed that reports every
Pokemon as changed on every run is worse than no change feed, because it is
confidently wrong and nobody can tell which entries are real.

The two properties that matter most are that reordering an array changes
nothing, and that a field we never read changes nothing.

Hashing has its own suite in test_hashing.py.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from api.sync.normalize import diff, normalize_pokemon


class TestShufflingChangesNothing:
    """The critical property. PokeAPI does not guarantee array ordering, so a
    naive hash of the raw payload reports a change on every single run."""

    def test_shuffled_arrays_normalise_identically(self, payload: dict[str, Any]) -> None:
        shuffled = copy.deepcopy(payload)
        rng = random.Random(0)
        for key in ("types", "stats", "abilities", "moves"):
            rng.shuffle(shuffled[key])
        assert normalize_pokemon(shuffled) == normalize_pokemon(payload)

    def test_shuffled_arrays_produce_no_changes(self, payload: dict[str, Any]) -> None:
        shuffled = copy.deepcopy(payload)
        rng = random.Random(1)
        for key in ("types", "stats", "abilities", "moves"):
            rng.shuffle(shuffled[key])
        assert diff(payload, shuffled) == []

    def test_reordered_mapping_keys_change_nothing(self, payload: dict[str, Any]) -> None:
        reordered = {key: payload[key] for key in reversed(list(payload))}
        assert diff(payload, reordered) == []

    def test_duplicate_moves_are_collapsed(self, payload: dict[str, Any]) -> None:
        """The same move can appear once per learn method."""
        duplicated = copy.deepcopy(payload)
        duplicated["moves"].append(duplicated["moves"][0])
        assert diff(payload, duplicated) == []


class TestUnconsumedFieldsAreDropped:
    """Proves the projection actually projects. Every one of these churns
    upstream and means nothing to us."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("base_experience", 999),
            ("order", 12345),
            ("species", {"name": "other", "url": "https://x"}),
            ("game_indices", [{"game_index": 1, "version": {"name": "blue"}}]),
            ("location_area_encounters", "https://elsewhere"),
            ("held_items", [{"item": {"name": "charcoal"}}]),
        ],
    )
    def test_changing_an_unread_field_produces_no_changes(
        self, payload: dict[str, Any], field: str, value: Any
    ) -> None:
        changed = copy.deepcopy(payload)
        changed[field] = value
        assert diff(payload, changed) == []

    def test_a_brand_new_upstream_field_is_ignored(self, payload: dict[str, Any]) -> None:
        """PokeAPI adding a field must not light up the change feed."""
        changed = copy.deepcopy(payload)
        changed["some_future_field"] = {"anything": [1, 2, 3]}
        assert diff(payload, changed) == []

    def test_unread_fields_do_not_appear_in_the_projection(self, payload: dict[str, Any]) -> None:
        normalized = normalize_pokemon(payload)
        for field in ("base_experience", "order", "species", "game_indices"):
            assert field not in normalized


class TestScalarChanges:
    def test_one_stat_change_is_exactly_one_record(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["stats"][1]["base_stat"] = 90  # attack 84 -> 90
        changes = diff(payload, changed)
        assert len(changes) == 1

    def test_stat_change_has_the_right_path_and_values(self, payload: dict[str, Any]) -> None:
        """'Attack 84 -> 90', not 'Charizard changed somehow'."""
        changed = copy.deepcopy(payload)
        changed["stats"][1]["base_stat"] = 90
        (change,) = diff(payload, changed)
        assert change.field_path == "stats.attack"
        assert (change.old_value, change.new_value) == ("84", "90")
        assert change.change_type == "changed"

    def test_sprite_change_is_one_record(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["sprites"]["front_default"] = "https://img/6-v2.png"
        (change,) = diff(payload, changed)
        assert change.field_path == "sprite"
        assert change.new_value == "https://img/6-v2.png"

    def test_sprite_removal_is_reported_as_removed(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["sprites"]["front_default"] = None
        (change,) = diff(payload, changed)
        assert change.change_type == "removed"
        assert change.new_value is None

    def test_type_change_reports_the_slot(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["types"][1]["type"]["name"] = "dragon"
        (change,) = diff(payload, changed)
        assert change.field_path == "types[1]"
        assert (change.old_value, change.new_value) == ("flying", "dragon")

    def test_swapping_type_slots_is_a_change(self, payload: dict[str, Any]) -> None:
        """Slot order is meaningful, so this must not be treated as a reshuffle."""
        changed = copy.deepcopy(payload)
        changed["types"] = [
            {"slot": 1, "type": {"name": "flying"}},
            {"slot": 2, "type": {"name": "fire"}},
        ]
        changes = diff(payload, changed)
        assert {c.field_path for c in changes} == {"types[0]", "types[1]"}

    def test_losing_a_secondary_type_is_a_removal(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["types"] = [{"slot": 1, "type": {"name": "fire"}}]
        (change,) = diff(payload, changed)
        assert change.field_path == "types[1]"
        assert change.change_type == "removed"
        assert (change.old_value, change.new_value) == ("flying", None)

    def test_height_and_weight_are_diffed(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["weight"] = 1000
        (change,) = diff(payload, changed)
        assert change.field_path == "weight"


class TestMovepoolMembership:
    """A movepool is a set. Learning a move must be one addition, not a
    cascade of index shifts through the rest of the list."""

    def test_added_move_is_one_addition(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["moves"].append(
            {"move": {"name": "earthquake", "url": "https://pokeapi.co/api/v2/move/89/"}}
        )
        (change,) = diff(payload, changed)
        assert change.field_path == "moves[89]"
        assert change.change_type == "added"
        assert (change.old_value, change.new_value) == (None, "89")

    def test_removed_move_is_one_removal(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["moves"] = [m for m in changed["moves"] if "move/19/" not in m["move"]["url"]]
        (change,) = diff(payload, changed)
        assert change.field_path == "moves[19]"
        assert change.change_type == "removed"
        assert (change.old_value, change.new_value) == ("19", None)

    def test_a_low_id_addition_does_not_shift_the_others(self, payload: dict[str, Any]) -> None:
        """Inserting id 1 sorts to the front. Positional comparison would report
        every move as changed; set comparison reports one addition."""
        changed = copy.deepcopy(payload)
        changed["moves"].append(
            {"move": {"name": "pound", "url": "https://pokeapi.co/api/v2/move/1/"}}
        )
        changes = diff(payload, changed)
        assert len(changes) == 1
        assert changes[0].field_path == "moves[1]"

    def test_simultaneous_add_and_remove(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["moves"] = [m for m in changed["moves"] if "move/10/" not in m["move"]["url"]]
        changed["moves"].append(
            {"move": {"name": "earthquake", "url": "https://pokeapi.co/api/v2/move/89/"}}
        )
        changes = {c.field_path: c.change_type for c in diff(payload, changed)}
        assert changes == {"moves[89]": "added", "moves[10]": "removed"}


class TestAbilities:
    def test_gained_ability_is_an_addition(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["abilities"].append({"ability": {"name": "drought"}, "is_hidden": False})
        (change,) = diff(payload, changed)
        assert change.field_path == "abilities.drought"
        assert change.change_type == "added"

    def test_hidden_flag_change_is_reported(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["abilities"][0]["is_hidden"] = True
        (change,) = diff(payload, changed)
        assert change.field_path == "abilities.blaze"
        assert (change.old_value, change.new_value) == ("False", "True")


class TestIdenticalPayloads:
    def test_no_changes(self, payload: dict[str, Any]) -> None:
        assert diff(payload, copy.deepcopy(payload)) == []


class TestDroppedFieldReporting:
    """`sprites` is consumed but re-emitted as the scalar `sprite`, so comparing
    output keys against input keys would wrongly report it as discarded."""

    def test_sprites_is_not_reported_as_dropped(self, payload: dict[str, Any]) -> None:
        from api.sync.normalize import dropped_fields

        assert "sprites" not in dropped_fields(payload)

    def test_genuinely_unread_fields_are_reported(self, payload: dict[str, Any]) -> None:
        from api.sync.normalize import dropped_fields

        reported = dropped_fields(payload)
        for field in ("base_experience", "order", "species", "game_indices"):
            assert field in reported

    # Every declared source field, with a mutation that must be visible. If one
    # of these stopped mattering, the declaration would be hiding a real change.
    MUTATIONS: dict[str, Any] = {
        "id": 7,
        "name": "charizard-mega-x",
        "types": [{"slot": 1, "type": {"name": "water"}}],
        "stats": [{"stat": {"name": "hp"}, "base_stat": 1}],
        "moves": [{"move": {"name": "pound", "url": "https://pokeapi.co/api/v2/move/1/"}}],
        "sprites": {"front_default": "https://img/other.png"},
        "abilities": [{"ability": {"name": "drought"}, "is_hidden": False}],
        "height": 99,
        "weight": 99,
        "is_default": False,
    }

    def test_the_mutation_table_covers_every_declared_field(self) -> None:
        from api.sync.normalize import CONSUMED_SOURCE_FIELDS

        assert set(self.MUTATIONS) == set(CONSUMED_SOURCE_FIELDS)

    @pytest.mark.parametrize("field", sorted(MUTATIONS))
    def test_changing_a_consumed_field_changes_the_projection(
        self, payload: dict[str, Any], field: str
    ) -> None:
        """id and name are required keys, so this mutates rather than strips."""
        changed = copy.deepcopy(payload)
        changed[field] = self.MUTATIONS[field]
        assert normalize_pokemon(changed) != normalize_pokemon(payload)
