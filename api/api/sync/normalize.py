"""Projection of raw PokeAPI payloads down to what we actually consume.

This is the most bug-prone code in the project, and the bugs are all false
positives rather than crashes. Hashing a raw payload directly reports a change
on every single run: PokeAPI does not guarantee array ordering, and the payload
carries dozens of fields we never read, any of which can churn upstream without
meaning anything to us.

Normalisation answers that by projecting to consumed fields only and ordering
every array deterministically. Everything downstream -- section hashes, diffs,
the change feed -- operates on the result, never on the raw payload.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

# Sections that get their own hash. Reporting "Attack 55 -> 60" rather than
# "Pikachu changed somehow" is the entire reason these are separate.
HASHED_SECTIONS: tuple[str, ...] = ("stats", "types", "moves", "sprite")

# Lists at these paths are compared as sets: a movepool is an unordered
# collection, so learning a move is an addition rather than a reshuffle of
# every index after it. Everything else is compared positionally, because
# `types` is ordered -- slot 1 and slot 2 are different facts about a Pokemon.
SET_LIKE_PATHS: frozenset[str] = frozenset({"moves"})

# Top-level keys of the raw payload that feed the projection. Not the same as
# the projection's own keys: `sprites` is read but re-emitted as the scalar
# `sprite`, so comparing output keys against input keys would report it as
# dropped. Used only for reporting what normalisation discards.
CONSUMED_SOURCE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "types",
        "stats",
        "moves",
        "sprites",
        "abilities",
        "height",
        "weight",
        "is_default",
    }
)


def dropped_fields(raw: dict[str, Any]) -> list[str]:
    """Top-level keys the projection discards. Changes to these are invisible."""
    return sorted(set(raw) - CONSUMED_SOURCE_FIELDS)


class _Missing:
    """Sentinel distinguishing 'absent' from 'present and None'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


MISSING = _Missing()

ChangeType = Literal["added", "removed", "changed"]


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One field-level difference between two normalised payloads."""

    field_path: str
    old_value: str | None
    new_value: str | None
    change_type: ChangeType


def _id_from_url(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[1])


def normalize_pokemon(payload: dict[str, Any]) -> dict[str, Any]:
    """Project a Pokemon payload to consumed fields, deterministically ordered.

    Every collection is given a stable order here rather than at comparison
    time, so two payloads describing the same Pokemon normalise to equal
    structures no matter what order PokeAPI returned their arrays in.
    """
    sprites = payload.get("sprites") or {}

    # Slot order is meaningful and therefore preserved, not sorted: fire/flying
    # and flying/fire are different Pokemon.
    types = [
        entry["type"]["name"] for entry in sorted(payload.get("types", []), key=lambda t: t["slot"])
    ]

    # Sorted and deduplicated: a movepool is a set, and PokeAPI's ordering of it
    # is not stable between responses.
    moves = sorted({_id_from_url(entry["move"]["url"]) for entry in payload.get("moves", [])})

    # A mapping rather than a list, so a gained or lost ability is a key
    # appearing or disappearing rather than every later index shifting.
    abilities = {
        entry["ability"]["name"]: bool(entry.get("is_hidden", False))
        for entry in payload.get("abilities", [])
    }

    return {
        "id": payload["id"],
        "name": payload["name"],
        # The four hashed sections. Their shapes are load-bearing: each is
        # hashed exactly as it appears here.
        "types": types,
        "stats": {entry["stat"]["name"]: entry["base_stat"] for entry in payload.get("stats", [])},
        "moves": moves,
        "sprite": sprites.get("front_default"),
        # Consumed and diffed, but not covered by a section hash.
        "abilities": abilities,
        "height": payload.get("height"),
        "weight": payload.get("weight"),
        "is_default": payload.get("is_default"),
    }


def _render(value: Any) -> str | None:
    """Render a value for storage in data_change.old_value / new_value."""
    if value is MISSING or value is None:
        return None
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


def _emit(path: str, old: Any, new: Any, out: list[FieldChange]) -> None:
    if old is MISSING or old is None:
        change_type: ChangeType = "added"
    elif new is MISSING or new is None:
        change_type = "removed"
    else:
        change_type = "changed"
    out.append(
        FieldChange(
            field_path=path,
            old_value=_render(old),
            new_value=_render(new),
            change_type=change_type,
        )
    )


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _walk(path: str, old: Any, new: Any, out: list[FieldChange]) -> None:
    if old is MISSING and new is MISSING:
        return

    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            _walk(_join(path, key), old.get(key, MISSING), new.get(key, MISSING), out)
        return

    if isinstance(old, list) and isinstance(new, list):
        if path in SET_LIKE_PATHS:
            _walk_set(path, old, new, out)
        else:
            _walk_sequence(path, old, new, out)
        return

    if old != new:
        _emit(path, old, new, out)


def _walk_set(path: str, old: list[Any], new: list[Any], out: list[FieldChange]) -> None:
    """Compare an unordered collection by membership.

    A learned move is one addition, not a cascade of index changes.
    """
    old_set, new_set = set(old), set(new)
    for item in sorted(new_set - old_set, key=str):
        _emit(f"{path}[{item}]", MISSING, item, out)
    for item in sorted(old_set - new_set, key=str):
        _emit(f"{path}[{item}]", item, MISSING, out)


def _walk_sequence(path: str, old: list[Any], new: list[Any], out: list[FieldChange]) -> None:
    """Compare an ordered collection positionally, including length changes."""
    for index in range(max(len(old), len(new))):
        _walk(
            f"{path}[{index}]",
            old[index] if index < len(old) else MISSING,
            new[index] if index < len(new) else MISSING,
            out,
        )


def diff_normalized(old: dict[str, Any], new: dict[str, Any]) -> list[FieldChange]:
    """Diff two already-normalised payloads."""
    changes: list[FieldChange] = []
    _walk("", old, new, changes)
    return sorted(changes, key=lambda change: change.field_path)


def diff(old_raw: dict[str, Any], new_raw: dict[str, Any]) -> list[FieldChange]:
    """Diff two raw payloads by normalising both first.

    Normalising both sides is what makes this trustworthy: a reordered array or
    a churned field we never read produces no records at all.
    """
    return diff_normalized(normalize_pokemon(old_raw), normalize_pokemon(new_raw))
