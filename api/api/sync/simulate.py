"""Deliberately diverge our snapshot from upstream, so detection is demonstrable.

This mutates OUR STORED COPY. It does not touch PokeAPI, and it cannot: the
upstream data is read-only to us. The next sync sees our altered values, reports
the difference, and writes the true upstream values back, which is why no reset
endpoint is needed.

Two traps this module exists to avoid:

Mutating only the hash. The sync gates on the section hash but produces its
detail by diffing the stored `raw` payload against the live fetch. Corrupt only
the hash and the sync finds a mismatch, diffs raw against upstream, finds
nothing, reports zero changes, and quietly repairs the hash -- a false negative
that looks exactly like a broken detector. So the raw payload is what gets
mutated, and everything else is recomputed from it.

Recomputing one section hash. Mutating stats and types on the same Pokemon has
to move stats_hash and types_hash. Rather than tracking which sections were
touched and updating those, the whole row is rebuilt from the mutated payload,
so a section cannot be missed.
"""

from __future__ import annotations

import copy
import enum
import random
from dataclasses import dataclass
from typing import Any

from api.ingest.normalize import CANONICAL_TYPES
from api.sync.alerts import alert_text


class MutationField(enum.StrEnum):
    """The groups of fields that can be diverged."""

    stats = "stats"
    types = "types"
    sprite = "sprite"
    moves = "moves"


# Ceiling for each group. `mutations_per_field` is clamped to these rather than
# rejected, and the effective value is reported back.
GROUP_MAXIMA: dict[str, int] = {
    MutationField.stats: 6,  # one per base stat
    MutationField.types: 2,  # primary and secondary
    MutationField.sprite: 1,  # a single URL
    MutationField.moves: 5,  # more than this makes the alert unreadable
}

MIN_STAT_SHIFT = 5
MAX_STAT_SHIFT = 25


@dataclass(frozen=True, slots=True)
class Mutation:
    """One discrete divergence, which becomes exactly one data_change row."""

    section: str
    field_path: str
    upstream_value: Any
    mutated_to: Any
    expect_alert: str


def _alert_for(name: str, field_path: str, mutation: tuple[Any, Any], move_name: str | None) -> str:
    """Predict the alert this divergence will produce.

    Note the inversion. Our snapshot now holds the mutated value, so the sync
    reads the change as mutated -> upstream: `old_value` is what we mutated to
    and `new_value` is the true upstream value.
    """
    mutated_to, upstream_value = mutation
    return alert_text(name, field_path, mutated_to, upstream_value, move_name=move_name)


def _mutate_stats(raw: dict[str, Any], count: int, rng: random.Random, name: str) -> list[Mutation]:
    """Shift distinct base stats, drawn without replacement."""
    entries = raw.get("stats", [])
    chosen = rng.sample(range(len(entries)), k=min(count, len(entries)))
    mutations: list[Mutation] = []
    for index in chosen:
        entry = entries[index]
        stat_name = entry["stat"]["name"]
        upstream = entry["base_stat"]
        shift = rng.choice([-1, 1]) * rng.randint(MIN_STAT_SHIFT, MAX_STAT_SHIFT)
        # Floor at 1: a base stat of zero would be a value the games never
        # produce, and the point is a believable divergence.
        mutated = max(1, upstream + shift)
        if mutated == upstream:
            mutated = upstream + MIN_STAT_SHIFT
        entry["base_stat"] = mutated
        field_path = f"stats.{stat_name}"
        mutations.append(
            Mutation(
                section="stats",
                field_path=field_path,
                upstream_value=upstream,
                mutated_to=mutated,
                expect_alert=_alert_for(name, field_path, (mutated, upstream), None),
            )
        )
    return mutations


def _mutate_types(raw: dict[str, Any], count: int, rng: random.Random, name: str) -> list[Mutation]:
    """Diverge a Pokemon's typing.

    Existing slots are replaced first. If more mutations are asked for than
    there are slots, a secondary type is added -- a real kind of upstream change
    and the only way a single-typed Pokemon can absorb two type mutations. The
    result never has type1 == type2 and never a non-canonical type.
    """
    entries = sorted(raw.get("types", []), key=lambda t: t["slot"])
    mutations: list[Mutation] = []

    replaceable = min(count, len(entries))
    for index in rng.sample(range(len(entries)), k=replaceable):
        entry = entries[index]
        upstream = entry["type"]["name"]
        others = {e["type"]["name"] for e in entries if e is not entry}
        options = [t for t in CANONICAL_TYPES if t != upstream and t not in others]
        if not options:
            continue
        mutated = rng.choice(options)
        entry["type"]["name"] = mutated
        field_path = f"types[{index}]"
        mutations.append(
            Mutation(
                section="types",
                field_path=field_path,
                upstream_value=upstream,
                mutated_to=mutated,
                expect_alert=_alert_for(name, field_path, (mutated, upstream), None),
            )
        )

    if count > len(entries) and len(entries) < GROUP_MAXIMA[MutationField.types]:
        taken = {e["type"]["name"] for e in entries}
        options = [t for t in CANONICAL_TYPES if t not in taken]
        if options:
            added = rng.choice(options)
            slot = len(entries) + 1
            entries.append({"slot": slot, "type": {"name": added}})
            field_path = f"types[{slot - 1}]"
            # We added a slot upstream does not have, so the sync will report it
            # as lost when it restores the true typing.
            mutations.append(
                Mutation(
                    section="types",
                    field_path=field_path,
                    upstream_value=None,
                    mutated_to=added,
                    expect_alert=alert_text(name, field_path, added, None),
                )
            )

    raw["types"] = entries
    return mutations


def _mutate_sprite(raw: dict[str, Any], name: str) -> list[Mutation]:
    """Append a marker to the sprite URL. There is only one, so this caps at 1."""
    sprites = raw.setdefault("sprites", {})
    upstream = sprites.get("front_default")
    if upstream is None:
        return []
    mutated = f"{upstream}?simulated=1"
    sprites["front_default"] = mutated
    return [
        Mutation(
            section="sprite",
            field_path="sprite",
            upstream_value=upstream,
            mutated_to=mutated,
            expect_alert=_alert_for(name, "sprite", (mutated, upstream), None),
        )
    ]


def _mutate_moves(
    raw: dict[str, Any],
    count: int,
    rng: random.Random,
    name: str,
    addable: list[tuple[int, str]],
) -> list[Mutation]:
    """Remove moves the Pokemon has and add ones it does not.

    Removals and additions alternate so a request for several move mutations
    exercises both directions.
    """
    entries = raw.get("moves", [])
    present = {int(e["move"]["url"].rstrip("/").rsplit("/", 1)[1]): e for e in entries}
    available_to_add = [m for m in addable if m[0] not in present]

    mutations: list[Mutation] = []
    removable = list(present)
    rng.shuffle(removable)
    add_queue = list(available_to_add)
    rng.shuffle(add_queue)

    for step in range(count):
        remove_turn = step % 2 == 0
        if remove_turn and removable:
            move_id = removable.pop()
            entry = present.pop(move_id)
            entries.remove(entry)
            move_name = entry["move"]["name"]
            field_path = f"moves[{move_id}]"
            # We removed it, so our snapshot lacks it and upstream has it: the
            # sync will report it as learned.
            mutations.append(
                Mutation(
                    section="moves",
                    field_path=field_path,
                    upstream_value=move_id,
                    mutated_to=None,
                    expect_alert=alert_text(name, field_path, None, move_id, move_name=move_name),
                )
            )
        elif add_queue:
            move_id, move_name = add_queue.pop()
            entries.append(
                {"move": {"name": move_name, "url": f"https://pokeapi.co/api/v2/move/{move_id}/"}}
            )
            present[move_id] = entries[-1]
            field_path = f"moves[{move_id}]"
            # We added it and upstream does not have it, so the sync reports it
            # as forgotten.
            mutations.append(
                Mutation(
                    section="moves",
                    field_path=field_path,
                    upstream_value=None,
                    mutated_to=move_id,
                    expect_alert=alert_text(name, field_path, move_id, None, move_name=move_name),
                )
            )
        elif removable:
            continue
        else:
            break
    return mutations


def mutate_payload(
    raw: dict[str, Any],
    name: str,
    groups: list[MutationField],
    mutations_per_field: int,
    rng: random.Random,
    addable_moves: list[tuple[int, str]],
) -> tuple[dict[str, Any], list[Mutation]]:
    """Apply every requested group to one payload.

    Returns the mutated payload and one Mutation per discrete change. Several
    groups on one Pokemon means several sections change on the same row, which
    is the case most likely to be got wrong.
    """
    mutated = copy.deepcopy(raw)
    mutations: list[Mutation] = []

    for group in groups:
        allowance = min(mutations_per_field, GROUP_MAXIMA[group])
        if group is MutationField.stats:
            mutations += _mutate_stats(mutated, allowance, rng, name)
        elif group is MutationField.types:
            mutations += _mutate_types(mutated, allowance, rng, name)
        elif group is MutationField.sprite:
            mutations += _mutate_sprite(mutated, name)
        elif group is MutationField.moves:
            mutations += _mutate_moves(mutated, allowance, rng, name, addable_moves)

    return mutated, mutations


def effective_allowances(groups: list[MutationField], mutations_per_field: int) -> dict[str, int]:
    """What each group's count was clamped to, for reporting back."""
    return {group.value: min(mutations_per_field, GROUP_MAXIMA[group]) for group in groups}
