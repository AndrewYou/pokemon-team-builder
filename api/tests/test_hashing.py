"""Tests for section hashing.

Change detection compares a freshly computed hash against one written to the
database days earlier, by a different process. So the property under test is
not "does this hash" but "does this hash *identically*, every time, everywhere".
Anything less turns the change feed into noise: every Pokemon reported as
changed on every run, with no way to tell which entries are real.

The projection these hashes run over is tested in test_normalize.py.
"""

from __future__ import annotations

import copy
import json
import random
import subprocess
import sys
from typing import Any

import pytest

from api.sync.hashing import digest, hash_pokemon, section_hash, section_hashes
from api.sync.normalize import HASHED_SECTIONS, normalize_pokemon

SHUFFLED_KEYS = ("types", "stats", "abilities", "moves")


class TestDigest:
    """The canonical encoding underneath every section hash."""

    def test_is_a_sha256_hex_digest(self) -> None:
        value = digest({"a": 1})
        assert len(value) == 64
        assert set(value) <= set("0123456789abcdef")

    def test_fits_the_database_column(self) -> None:
        """Pokemon.stats_hash is String(64). A longer digest would be truncated
        or rejected, and truncation would silently weaken every comparison."""
        assert len(digest({"a": 1})) == 64

    def test_is_deterministic(self) -> None:
        assert digest({"a": 1, "b": [1, 2]}) == digest({"a": 1, "b": [1, 2]})

    def test_ignores_mapping_key_order(self) -> None:
        """Python preserves insertion order, and JSON payloads do not arrive in
        a guaranteed one."""
        assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})

    def test_ignores_nested_mapping_key_order(self) -> None:
        assert digest({"x": {"a": 1, "b": 2}}) == digest({"x": {"b": 2, "a": 1}})

    def test_respects_sequence_order(self) -> None:
        """Ordering is meaningful for sequences, so it must survive. Types are
        stored as an ordered list precisely because slot order matters."""
        assert digest([1, 2]) != digest([2, 1])

    def test_distinguishes_different_values(self) -> None:
        assert digest({"a": 1}) != digest({"a": 2})

    def test_distinguishes_types_from_their_string_forms(self) -> None:
        """`default=str` coerces unserialisable values, so this checks the
        coercion does not collapse genuinely different data."""
        assert digest(1) != digest("1")

    def test_distinguishes_null_from_absent(self) -> None:
        assert digest({"a": None}) != digest({})

    def test_distinguishes_empty_containers(self) -> None:
        assert digest([]) != digest({})

    def test_handles_none(self) -> None:
        assert len(digest(None)) == 64

    def test_handles_unicode(self) -> None:
        assert digest("Pokémon") != digest("Pokemon")

    def test_uses_compact_separators(self) -> None:
        """Whitespace in the encoding would be a second way to represent the
        same data, and therefore a second hash for it."""
        assert digest({"a": 1}) == digest(json.loads('{"a": 1}'))


class TestSectionHashShape:
    def test_covers_every_hashed_section(self, payload: dict[str, Any]) -> None:
        assert set(hash_pokemon(payload)) == {f"{s}_hash" for s in HASHED_SECTIONS}

    def test_keys_match_the_database_columns(self, payload: dict[str, Any]) -> None:
        assert set(hash_pokemon(payload)) == {
            "stats_hash",
            "types_hash",
            "moves_hash",
            "sprite_hash",
        }

    def test_sections_hash_differently(self, payload: dict[str, Any]) -> None:
        """Four identical hashes would mean the sections carry no information."""
        assert len(set(hash_pokemon(payload).values())) == 4

    def test_section_hash_matches_the_bulk_call(self, payload: dict[str, Any]) -> None:
        normalized = normalize_pokemon(payload)
        assert section_hash(normalized, "stats") == section_hashes(normalized)["stats_hash"]

    def test_missing_section_still_hashes(self) -> None:
        """A section absent from the projection hashes as null rather than
        raising, so a malformed payload cannot take down a sync mid-run."""
        assert len(section_hash({}, "stats")) == 64


class TestOrderingInvariance:
    """The property that makes hashing usable at all. PokeAPI does not
    guarantee array ordering, so a hash sensitive to it reports a change on
    every single run."""

    def test_shuffled_arrays_hash_identically(self, payload: dict[str, Any]) -> None:
        shuffled = copy.deepcopy(payload)
        rng = random.Random(2)
        for key in SHUFFLED_KEYS:
            rng.shuffle(shuffled[key])
        assert hash_pokemon(shuffled) == hash_pokemon(payload)

    def test_holds_across_many_shuffles(self, payload: dict[str, Any]) -> None:
        """One lucky ordering proves nothing."""
        expected = hash_pokemon(payload)
        rng = random.Random(3)
        for _ in range(100):
            shuffled = copy.deepcopy(payload)
            for key in SHUFFLED_KEYS:
                rng.shuffle(shuffled[key])
            assert hash_pokemon(shuffled) == expected

    @pytest.mark.parametrize("key", SHUFFLED_KEYS)
    def test_each_array_independently(self, payload: dict[str, Any], key: str) -> None:
        reversed_payload = copy.deepcopy(payload)
        reversed_payload[key] = list(reversed(reversed_payload[key]))
        assert hash_pokemon(reversed_payload) == hash_pokemon(payload)

    def test_duplicate_moves_hash_identically(self, payload: dict[str, Any]) -> None:
        """A move appears once per learn method upstream."""
        duplicated = copy.deepcopy(payload)
        duplicated["moves"].append(duplicated["moves"][0])
        assert hash_pokemon(duplicated) == hash_pokemon(payload)

    def test_a_deep_copy_hashes_identically(self, payload: dict[str, Any]) -> None:
        assert hash_pokemon(payload) == hash_pokemon(copy.deepcopy(payload))


class TestSectionIsolation:
    """Section hashes exist so a change can be attributed. If one change moved
    every hash, four hashes would say no more than one."""

    def _hashes(self, payload: dict[str, Any]) -> dict[str, str]:
        return hash_pokemon(payload)

    def _assert_only(self, before: dict[str, str], after: dict[str, str], moved: str) -> None:
        assert before[moved] != after[moved], f"{moved} should have changed"
        for section in before:
            if section != moved:
                assert before[section] == after[section], f"{section} moved unexpectedly"

    def test_stat_change_moves_only_stats_hash(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["stats"][1]["base_stat"] = 90
        self._assert_only(self._hashes(payload), self._hashes(changed), "stats_hash")

    def test_type_change_moves_only_types_hash(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["types"][1]["type"]["name"] = "dragon"
        self._assert_only(self._hashes(payload), self._hashes(changed), "types_hash")

    def test_added_move_moves_only_moves_hash(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["moves"].append(
            {"move": {"name": "earthquake", "url": "https://pokeapi.co/api/v2/move/89/"}}
        )
        self._assert_only(self._hashes(payload), self._hashes(changed), "moves_hash")

    def test_removed_move_moves_only_moves_hash(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["moves"] = changed["moves"][:-1]
        self._assert_only(self._hashes(payload), self._hashes(changed), "moves_hash")

    def test_sprite_change_moves_only_sprite_hash(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["sprites"]["front_default"] = "https://img/6-v2.png"
        self._assert_only(self._hashes(payload), self._hashes(changed), "sprite_hash")

    def test_sprite_removal_moves_only_sprite_hash(self, payload: dict[str, Any]) -> None:
        changed = copy.deepcopy(payload)
        changed["sprites"]["front_default"] = None
        self._assert_only(self._hashes(payload), self._hashes(changed), "sprite_hash")


class TestUnhashedChanges:
    """Fields outside the four sections must not move any hash."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("base_experience", 999),
            ("order", 12345),
            ("species", {"name": "other", "url": "https://x"}),
            ("game_indices", [{"game_index": 1, "version": {"name": "blue"}}]),
        ],
    )
    def test_unconsumed_field_moves_no_hash(
        self, payload: dict[str, Any], field: str, value: Any
    ) -> None:
        changed = copy.deepcopy(payload)
        changed[field] = value
        assert hash_pokemon(changed) == hash_pokemon(payload)

    @pytest.mark.parametrize("field", ["height", "weight", "is_default"])
    def test_consumed_but_unhashed_fields_move_no_hash(
        self, payload: dict[str, Any], field: str
    ) -> None:
        """A known gap, asserted rather than left implicit: these are diffed but
        no section hash covers them, so a sync using hashes as its only signal
        would not notice them change."""
        changed = copy.deepcopy(payload)
        changed[field] = 12345 if field != "is_default" else False
        assert hash_pokemon(changed) == hash_pokemon(payload)

    def test_ability_change_moves_no_hash(self, payload: dict[str, Any]) -> None:
        """Same gap: abilities are diffed but unhashed."""
        changed = copy.deepcopy(payload)
        changed["abilities"].append({"ability": {"name": "drought"}, "is_hidden": False})
        assert hash_pokemon(changed) == hash_pokemon(payload)


class TestCrossProcessStability:
    """A hash is written by the seed and compared by a sync days later, in a
    different process. Python randomises string hashing per process, so
    anything depending on set or dict iteration order would differ between the
    two and report every Pokemon as changed."""

    SCRIPT = (
        "import json,sys;"
        "sys.path.insert(0, 'tests');"
        "from conftest import _payload;"
        "from api.sync.hashing import hash_pokemon;"
        "print(json.dumps(hash_pokemon(_payload())))"
    )

    def _hash_in_subprocess(self, seed: str) -> dict[str, str]:
        result = subprocess.run(
            [sys.executable, "-c", self.SCRIPT],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        return dict(json.loads(result.stdout))

    def test_identical_under_different_hash_seeds(self) -> None:
        assert self._hash_in_subprocess("0") == self._hash_in_subprocess("12345")

    def test_subprocess_matches_this_process(self, payload: dict[str, Any]) -> None:
        assert self._hash_in_subprocess("0") == hash_pokemon(payload)


class TestGoldenHashes:
    """Pinned values for a fixed payload.

    These are stored in the database by the seed, so changing normalisation
    changes them and invalidates every stored hash. That is a legitimate thing
    to do, but it requires a reseed: until then the next sync reports every
    Pokemon as changed. This test exists so that consequence is a deliberate
    decision rather than a surprise.
    """

    EXPECTED = {
        "stats_hash": "ab211e7f8815baa2ca802a5f32b3ec1dc97328a68c85b84f199767ae3408cb11",
        "types_hash": "f3259c63ec7622970f3a491a4003544268eecd9198aabf84e07cd3462907c72b",
        "moves_hash": "70c83dbed7c1ccd0577aba32f35ef3c2ec4e370ffcf26a12295ebad5c0e61716",
        "sprite_hash": "231ce2ca9c840ac0a5fbbae46b56147673c689631de2f4d02b55dc6ed4db6957",
    }

    def test_hashes_are_unchanged(self, payload: dict[str, Any]) -> None:
        assert hash_pokemon(payload) == self.EXPECTED


class TestIngestAgreesWithSync:
    """The seed writes these hashes and the sync compares against them. Two
    implementations would drift, and drift makes every row look changed."""

    @pytest.mark.parametrize(
        ("section", "function_name"),
        [
            ("stats", "stats_hash"),
            ("types", "types_hash"),
            ("moves", "moves_hash"),
            ("sprite", "sprite_hash"),
        ],
    )
    def test_ingest_helper_matches_the_section_hash(
        self, payload: dict[str, Any], section: str, function_name: str
    ) -> None:
        from api.ingest import normalize as ingest_normalize

        helper = getattr(ingest_normalize, function_name)
        assert helper(payload) == section_hash(normalize_pokemon(payload), section)

    def test_pokemon_row_carries_the_same_hashes(self, payload: dict[str, Any]) -> None:
        from api.ingest.normalize import pokemon_row

        row = pokemon_row(payload)
        expected = hash_pokemon(payload)
        assert {key: row[key] for key in expected} == expected
