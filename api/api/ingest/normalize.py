"""Pure transforms from PokeAPI payloads to database rows.

Nothing here touches the network or the database, which is what makes the sync
behaviour testable. The hash helpers are the foundation of change detection:
they must be stable across runs and across machines, so every structure is
canonicalised (keys sorted, lists ordered) before it is digested.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

# The 18 battle types. PokeAPI also serves `unknown`, `shadow`, and `stellar`,
# which are not part of the effectiveness chart and would break the 18x18 = 324
# invariant if they were included.
CANONICAL_TYPES: tuple[str, ...] = (
    "normal",
    "fighting",
    "flying",
    "poison",
    "ground",
    "rock",
    "bug",
    "ghost",
    "steel",
    "fire",
    "water",
    "grass",
    "electric",
    "psychic",
    "ice",
    "dragon",
    "dark",
    "fairy",
)

_STAT_COLUMNS = {
    "hp": "base_hp",
    "attack": "base_atk",
    "defense": "base_def",
    "special-attack": "base_spatk",
    "special-defense": "base_spdef",
    "speed": "base_speed",
}

# Dropped from the stored payload. `version_group_details` alone is ~90% of a
# Pokemon response -- per-move, per-game learn data we never read. Keeping it
# would make the fixture ~400 MB and blow the database's storage budget.
_POKEMON_DROP = frozenset(
    {
        "game_indices",
        "held_items",
        "past_abilities",
        "past_types",
        "location_area_encounters",
        "forms",
        "cries",
    }
)

_MOVE_DROP = frozenset(
    {
        "flavor_text_entries",
        "learned_by_pokemon",
        "machines",
        "names",
        "contest_combos",
        "contest_effect",
        "super_contest_effect",
        "past_values",
        "effect_changes",
    }
)


def digest(value: Any) -> str:
    """Stable sha256 of any JSON-serialisable structure."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def id_from_url(url: str) -> int:
    """Extract the trailing numeric id from a PokeAPI resource URL."""
    return int(url.rstrip("/").rsplit("/", 1)[1])


def trim_pokemon(payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Pokemon payload to what we actually store.

    Deliberately lossy. `raw` exists to backfill new columns without refetching,
    so anything dropped here cannot be backfilled later -- but retaining it is
    not affordable, and the discarded sections are all per-game trivia.
    """
    trimmed = {key: value for key, value in payload.items() if key not in _POKEMON_DROP}
    trimmed["moves"] = [{"move": entry["move"]} for entry in payload.get("moves", [])]
    sprites = payload.get("sprites") or {}
    trimmed["sprites"] = {"front_default": sprites.get("front_default")}
    return trimmed


def trim_move(payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce a move payload to what we actually store."""
    return {key: value for key, value in payload.items() if key not in _MOVE_DROP}


def trim_type(payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce a type payload to the effectiveness data we consume.

    A full type payload is ~35 KB, almost all of it the list of every Pokemon
    and move of that type. The chart only needs the damage relations.

    `past_damage_relations` is dropped deliberately, not incidentally. It holds
    superseded generation-specific charts -- Gen 1 had bug 2x into poison, ice
    1x into fire, ghost 0x into psychic -- and reading it would produce a chart
    that silently disagrees with the modern one.
    """
    return {
        "id": payload["id"],
        "name": payload["name"],
        "damage_relations": payload["damage_relations"],
    }


def stats_hash(payload: dict[str, Any]) -> str:
    return digest({s["stat"]["name"]: s["base_stat"] for s in payload.get("stats", [])})


def types_hash(payload: dict[str, Any]) -> str:
    return digest(type_names(payload))


def moves_hash(payload: dict[str, Any]) -> str:
    return digest(sorted(move_ids(payload)))


def sprite_hash(payload: dict[str, Any]) -> str:
    sprites = payload.get("sprites") or {}
    return digest(sprites.get("front_default"))


def move_content_hash(payload: dict[str, Any]) -> str:
    return digest(
        {
            "type": payload["type"]["name"],
            "damage_class": payload["damage_class"]["name"],
            "power": payload.get("power"),
            "accuracy": payload.get("accuracy"),
            "priority": payload.get("priority"),
            "effect_chance": payload.get("effect_chance"),
        }
    )


def type_names(payload: dict[str, Any]) -> list[str]:
    """Type names in slot order."""
    entries = sorted(payload.get("types", []), key=lambda t: t["slot"])
    return [entry["type"]["name"] for entry in entries]


def move_ids(payload: dict[str, Any]) -> list[int]:
    """Distinct move ids a Pokemon can learn, in ascending order."""
    return sorted({id_from_url(entry["move"]["url"]) for entry in payload.get("moves", [])})


def pokemon_row(payload: dict[str, Any]) -> dict[str, Any]:
    """One row for the `pokemon` table.

    Stats are written through untouched. Converting to level 50 here would make
    the next sync compare converted values against freshly fetched base ones,
    and every row would look changed on every run.
    """
    stats = {s["stat"]["name"]: s["base_stat"] for s in payload["stats"]}
    types = type_names(payload)
    sprites = payload.get("sprites") or {}

    row: dict[str, Any] = {
        "id": payload["id"],
        "name": payload["name"],
        "sprite_url": sprites.get("front_default"),
        "type1": types[0],
        "type2": types[1] if len(types) > 1 else None,
        "height": payload["height"],
        "weight": payload["weight"],
        "is_default": payload["is_default"],
        "raw": trim_pokemon(payload),
        "stats_hash": stats_hash(payload),
        "types_hash": types_hash(payload),
        "moves_hash": moves_hash(payload),
        "sprite_hash": sprite_hash(payload),
    }
    for api_name, column in _STAT_COLUMNS.items():
        row[column] = stats[api_name]
    return row


def move_row(payload: dict[str, Any]) -> dict[str, Any]:
    """One row for the `move` table."""
    return {
        "id": payload["id"],
        "name": payload["name"],
        "type": payload["type"]["name"],
        "damage_class": payload["damage_class"]["name"],
        "power": payload.get("power"),
        "accuracy": payload.get("accuracy"),
        # Priority is 0 for almost every move, but the field is genuinely
        # nullable-looking in the payload; treat a missing value as 0.
        "priority": payload.get("priority") or 0,
        "effect_chance": payload.get("effect_chance"),
        "raw": trim_move(payload),
        "content_hash": move_content_hash(payload),
    }


def pokemon_move_rows(payload: dict[str, Any], known_move_ids: set[int]) -> list[dict[str, Any]]:
    """Join rows, filtered to moves we actually stored.

    PokeAPI lists moves for a Pokemon that may not appear in the move index we
    fetched. Inserting those would violate the foreign key, so they are dropped
    here rather than blowing up the whole batch.
    """
    return [
        {"pokemon_id": payload["id"], "move_id": move_id}
        for move_id in move_ids(payload)
        if move_id in known_move_ids
    ]


def pokemon_ability_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Ability rows, deduplicated on name."""
    seen: dict[str, dict[str, Any]] = {}
    for entry in payload.get("abilities", []):
        name = entry["ability"]["name"]
        seen[name] = {
            "pokemon_id": payload["id"],
            "ability_name": name,
            "is_hidden": bool(entry.get("is_hidden", False)),
        }
    return list(seen.values())


# The chart is a known quantity, so the derivation checks its own work. These
# counts are the current (Gen 6+) chart, confirmed against pokemondb.net/type.
EXPECTED_TYPE_CHART_ROWS = len(CANONICAL_TYPES) ** 2
EXPECTED_MULTIPLIER_DISTRIBUTION: dict[str, int] = {"0": 8, "0.5": 61, "1": 204, "2": 51}


class TypeChartValidationError(ValueError):
    """The derived chart does not match the known-good shape."""


def format_multiplier(value: Decimal | float) -> str:
    """Stable string key for a multiplier: 0.5 stays '0.5', 1.0 becomes '1'."""
    return f"{float(value):g}"


def multiplier_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many pairings landed on each multiplier, ordered by value."""
    counts: dict[str, int] = {}
    for row in rows:
        key = format_multiplier(row["multiplier"])
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: float(item[0])))


def validate_type_chart(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Fail loudly unless the chart is exactly the one we expect.

    A chart that is merely plausible is the worst outcome here: every damage
    number downstream would be wrong in a way no test of *this* code would
    catch. The two ways to get a plausible-but-wrong chart are reading
    `past_damage_relations` instead of `damage_relations`, and failing to
    filter out the non-battle types, so both are caught by the counts.
    """
    distribution = multiplier_distribution(rows)
    if len(rows) != EXPECTED_TYPE_CHART_ROWS:
        raise TypeChartValidationError(
            f"expected {EXPECTED_TYPE_CHART_ROWS} rows "
            f"({len(CANONICAL_TYPES)} attacking x {len(CANONICAL_TYPES)} defending), "
            f"built {len(rows)}. Check that non-battle types "
            f"(unknown, shadow, stellar) were filtered out."
        )
    if distribution != EXPECTED_MULTIPLIER_DISTRIBUTION:
        raise TypeChartValidationError(
            f"multiplier distribution {distribution} does not match the known chart "
            f"{EXPECTED_MULTIPLIER_DISTRIBUTION}. A mismatch usually means "
            f"past_damage_relations was read instead of damage_relations."
        )
    return distribution


def type_chart_rows(type_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the full 18x18 effectiveness matrix.

    Every pair is emitted, defaulting to 1x, so the table is exactly 324 rows
    and a lookup never has to handle a missing combination.
    """
    canonical = set(CANONICAL_TYPES)
    # `damage_relations`, never `past_damage_relations`. The latter holds
    # superseded generation-specific charts and would produce a chart that
    # disagrees with the modern one without failing anywhere obvious.
    #
    # Filtering on the 18-name allowlist rather than on "types that have
    # pokemon": the stored payloads are trimmed and no longer carry a pokemon
    # list, and the allowlist also excludes `stellar`, which is a real Gen 9
    # type entry that a two-name unknown/shadow filter would let through.
    relations = {
        payload["name"]: payload["damage_relations"]
        for payload in type_payloads
        if payload["name"] in canonical
    }
    missing = canonical - set(relations)
    if missing:
        raise TypeChartValidationError(f"missing damage_relations for types: {sorted(missing)}")

    rows: list[dict[str, Any]] = []
    for attacking in CANONICAL_TYPES:
        damage = relations[attacking]
        multipliers: dict[str, Decimal] = {}
        for entry in damage["double_damage_to"]:
            multipliers[entry["name"]] = Decimal("2")
        for entry in damage["half_damage_to"]:
            multipliers[entry["name"]] = Decimal("0.5")
        for entry in damage["no_damage_to"]:
            multipliers[entry["name"]] = Decimal("0")

        for defending in CANONICAL_TYPES:
            rows.append(
                {
                    "attacking_type": attacking,
                    "defending_type": defending,
                    "multiplier": multipliers.get(defending, Decimal("1")),
                }
            )
    return rows
