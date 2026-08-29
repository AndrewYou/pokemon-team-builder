"""Tests for the change simulator.

The simulator's job is to create a divergence the sync will find. The failure
mode that matters is not a crash but a *partial* mutation: touching two groups
while only one section hash moves, so the sync reports half of what was done and
looks like a broken detector.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from api.ingest.normalize import CANONICAL_TYPES, pokemon_row
from api.sync.hashing import section_hashes
from api.sync.normalize import diff, normalize_pokemon
from api.sync.simulate import (
    GROUP_MAXIMA,
    MutationField,
    effective_allowances,
    mutate_payload,
)

ADDABLE = [(1, "pound"), (85, "thunderbolt"), (89, "earthquake"), (7, "vice-grip")]


@pytest.fixture
def rng() -> random.Random:
    return random.Random(1234)


def _mutate(
    payload: dict[str, Any],
    groups: list[MutationField],
    per_field: int,
    rng: random.Random,
) -> tuple[dict[str, Any], list[Any]]:
    return mutate_payload(payload, payload["name"], groups, per_field, rng, ADDABLE)


class TestRawIsMutated:
    """The sync gates on the hash but diffs the raw payload. Mutating only the
    hash would make it detect a mismatch, find nothing to report, and quietly
    repair the hash -- a false negative that looks like a broken detector."""

    def test_payload_actually_changes(self, payload: dict[str, Any], rng: random.Random) -> None:
        mutated, _ = _mutate(payload, [MutationField.stats], 1, rng)
        assert mutated != payload

    def test_original_is_left_alone(self, payload: dict[str, Any], rng: random.Random) -> None:
        before = copy.deepcopy(payload)
        _mutate(payload, [MutationField.stats], 2, rng)
        assert payload == before

    def test_the_diff_finds_exactly_the_mutations(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        """The count the endpoint promises is the count the sync will produce."""
        mutated, mutations = _mutate(
            payload, [MutationField.stats, MutationField.types, MutationField.sprite], 2, rng
        )
        assert len(diff(mutated, payload)) == len(mutations)

    def test_reported_paths_are_the_paths_the_diff_emits(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        mutated, mutations = _mutate(payload, [MutationField.stats, MutationField.types], 2, rng)
        assert {m.field_path for m in mutations} == {c.field_path for c in diff(mutated, payload)}


class TestSectionHashes:
    """Mutating several groups on one Pokemon must move several section hashes.
    Recomputing only the first is the most likely bug here."""

    def test_stats_only_moves_stats_hash(self, payload: dict[str, Any], rng: random.Random) -> None:
        mutated, _ = _mutate(payload, [MutationField.stats], 2, rng)
        before = section_hashes(normalize_pokemon(payload))
        after = section_hashes(normalize_pokemon(mutated))
        assert before["stats_hash"] != after["stats_hash"]
        assert before["types_hash"] == after["types_hash"]

    def test_three_groups_move_three_hashes(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        mutated, _ = _mutate(
            payload, [MutationField.stats, MutationField.types, MutationField.sprite], 2, rng
        )
        before = section_hashes(normalize_pokemon(payload))
        after = section_hashes(normalize_pokemon(mutated))
        moved = {k for k in before if before[k] != after[k]}
        assert moved == {"stats_hash", "types_hash", "sprite_hash"}

    def test_rebuilding_the_row_recomputes_every_hash(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        """The row is rebuilt wholesale from the mutated payload, so no section
        can be left holding a stale hash."""
        mutated, _ = _mutate(payload, [MutationField.stats, MutationField.types], 2, rng)
        row = pokemon_row(mutated)
        assert {k: row[k] for k in section_hashes(normalize_pokemon(mutated))} == section_hashes(
            normalize_pokemon(mutated)
        )

    def test_denormalised_columns_follow_the_payload(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        mutated, mutations = _mutate(payload, [MutationField.stats], 6, rng)
        row = pokemon_row(mutated)
        for mutation in mutations:
            stat = mutation.field_path.removeprefix("stats.")
            column = {
                "hp": "base_hp",
                "attack": "base_atk",
                "defense": "base_def",
                "special-attack": "base_spatk",
                "special-defense": "base_spdef",
                "speed": "base_speed",
            }[stat]
            assert row[column] == mutation.mutated_to


class TestWithoutReplacement:
    def test_stats_are_never_mutated_twice(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        _, mutations = _mutate(payload, [MutationField.stats], 6, rng)
        paths = [m.field_path for m in mutations]
        assert len(paths) == len(set(paths))

    def test_every_stat_can_be_mutated(self, payload: dict[str, Any], rng: random.Random) -> None:
        _, mutations = _mutate(payload, [MutationField.stats], 6, rng)
        assert len(mutations) == 6


class TestClamping:
    @pytest.mark.parametrize(
        ("group", "maximum"),
        [(MutationField.stats, 6), (MutationField.types, 2), (MutationField.sprite, 1)],
    )
    def test_requests_above_the_maximum_are_clamped_not_rejected(
        self, payload: dict[str, Any], rng: random.Random, group: MutationField, maximum: int
    ) -> None:
        _, mutations = _mutate(payload, [group], 99, rng)
        assert len(mutations) <= maximum

    def test_effective_allowances_report_the_clamp(self) -> None:
        allowances = effective_allowances(list(MutationField), 99)
        assert allowances == {g.value: GROUP_MAXIMA[g] for g in MutationField}

    def test_sprite_caps_at_one(self, payload: dict[str, Any], rng: random.Random) -> None:
        _, mutations = _mutate(payload, [MutationField.sprite], 5, rng)
        assert len(mutations) == 1


class TestTypes:
    def test_never_assigns_a_non_canonical_type(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        for seed in range(30):
            mutated, _ = _mutate(payload, [MutationField.types], 2, random.Random(seed))
            for entry in mutated["types"]:
                assert entry["type"]["name"] in CANONICAL_TYPES

    def test_never_produces_a_duplicate_type(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        for seed in range(30):
            mutated, _ = _mutate(payload, [MutationField.types], 2, random.Random(seed))
            names = [e["type"]["name"] for e in mutated["types"]]
            assert len(names) == len(set(names))

    def test_a_single_typed_pokemon_can_gain_a_second(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        """Otherwise a mono-type absorbs only one type mutation, and the counts
        a caller was promised would not add up."""
        payload["types"] = [{"slot": 1, "type": {"name": "electric"}}]
        _, mutations = _mutate(payload, [MutationField.types], 2, rng)
        assert len(mutations) == 2
        assert any(m.upstream_value is None for m in mutations)


class TestMultiField:
    def test_every_listed_group_is_applied(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        groups = [MutationField.stats, MutationField.types, MutationField.sprite]
        _, mutations = _mutate(payload, groups, 2, rng)
        assert {m.section for m in mutations} == {g.value for g in groups}

    def test_counts_match_the_documented_arithmetic(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        """2 stats + 2 types + 1 sprite = 5 per dual-typed Pokemon."""
        groups = [MutationField.stats, MutationField.types, MutationField.sprite]
        _, mutations = _mutate(payload, groups, 2, rng)
        assert len(mutations) == 5

    def test_each_change_is_its_own_record(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        """Two stat changes are two entries, never collapsed into one."""
        _, mutations = _mutate(payload, [MutationField.stats], 2, rng)
        assert len(mutations) == 2


class TestInversion:
    """Our snapshot now holds the mutated value, so the sync reads the change as
    mutated -> upstream. This confuses people every time."""

    def test_expect_alert_reads_from_mutated_to_upstream(
        self, payload: dict[str, Any], rng: random.Random
    ) -> None:
        _, mutations = _mutate(payload, [MutationField.stats], 1, rng)
        mutation = mutations[0]
        assert f"from {mutation.mutated_to} to {mutation.upstream_value}" in mutation.expect_alert

    def test_diff_confirms_the_direction(self, payload: dict[str, Any], rng: random.Random) -> None:
        """Diffing mutated-as-stored against upstream must yield old=mutated."""
        mutated, mutations = _mutate(payload, [MutationField.stats], 1, rng)
        change = diff(mutated, payload)[0]
        assert change.old_value == str(mutations[0].mutated_to)
        assert change.new_value == str(mutations[0].upstream_value)
