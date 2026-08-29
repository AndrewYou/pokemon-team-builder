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


class TestRepeatedMutation:
    """simulate-change may run several times before a sync.

    The reported `upstream_value` has to come from the reference payload, not
    from what we currently hold. Reading it from our own already-mutated copy
    predicts an alert the sync will never produce -- which breaks the one thing
    the endpoint is for, since the demo turns on comparing the prediction
    against the alert word for word.
    """

    def test_second_run_reports_the_true_upstream_value(self, payload: dict[str, Any]) -> None:
        reference = copy.deepcopy(payload)
        rng = random.Random(7)

        once, first = mutate_payload(
            payload, payload["name"], [MutationField.stats], 6, rng, ADDABLE, reference=reference
        )
        twice, second = mutate_payload(
            once, payload["name"], [MutationField.stats], 6, rng, ADDABLE, reference=reference
        )

        upstream_by_path = {m.field_path: m.upstream_value for m in first}
        for mutation in second:
            assert mutation.upstream_value == upstream_by_path[mutation.field_path], (
                f"{mutation.field_path} reported our own mutation as upstream"
            )

    def test_the_latest_prediction_matches_what_a_diff_would_find(
        self, payload: dict[str, Any]
    ) -> None:
        """The end state versus the truth is what the sync compares."""
        reference = copy.deepcopy(payload)
        rng = random.Random(11)

        once, _ = mutate_payload(
            payload, payload["name"], [MutationField.stats], 3, rng, ADDABLE, reference=reference
        )
        twice, second = mutate_payload(
            once, payload["name"], [MutationField.stats], 3, rng, ADDABLE, reference=reference
        )

        changes = {c.field_path: (c.old_value, c.new_value) for c in diff(twice, reference)}
        for mutation in second:
            old, new = changes[mutation.field_path]
            assert old == str(mutation.mutated_to)
            assert new == str(mutation.upstream_value)

    def test_sprite_markers_do_not_stack(self, payload: dict[str, Any]) -> None:
        """Built from the true URL each time, so a second run does not report an
        already-marked URL as though upstream had served it."""
        reference = copy.deepcopy(payload)
        rng = random.Random(3)
        once, first = mutate_payload(
            payload, payload["name"], [MutationField.sprite], 1, rng, ADDABLE, reference=reference
        )
        _, second = mutate_payload(
            once, payload["name"], [MutationField.sprite], 1, rng, ADDABLE, reference=reference
        )
        assert first[0].upstream_value == second[0].upstream_value
        assert second[0].upstream_value == reference["sprites"]["front_default"]

    def test_moves_are_only_removed_if_upstream_has_them(self, payload: dict[str, Any]) -> None:
        """Removing a move a previous run added would cancel out, producing a
        mutation the sync cannot report."""
        reference = copy.deepcopy(payload)
        rng = random.Random(5)
        once, _ = mutate_payload(
            payload, payload["name"], [MutationField.moves], 4, rng, ADDABLE, reference=reference
        )
        _, second = mutate_payload(
            once, payload["name"], [MutationField.moves], 4, rng, ADDABLE, reference=reference
        )
        upstream_ids = {
            int(e["move"]["url"].rstrip("/").rsplit("/", 1)[1]) for e in reference["moves"]
        }
        for mutation in second:
            move_id = int(mutation.field_path[6:-1])
            if mutation.mutated_to is None:
                assert move_id in upstream_ids, "removed a move upstream never had"
            else:
                assert move_id not in upstream_ids, "added a move upstream already has"

    def test_defaults_to_the_payload_when_no_reference_is_given(
        self, payload: dict[str, Any]
    ) -> None:
        """A caller holding a clean snapshot need not pass one."""
        _, mutations = mutate_payload(
            payload, payload["name"], [MutationField.stats], 1, random.Random(1), ADDABLE
        )
        assert mutations
