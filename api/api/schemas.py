"""Pydantic request/response schemas.

Routes never return ORM objects directly. Every model carries a realistic
example so that Swagger's "Try it out" pre-fills with a working payload rather
than an empty skeleton -- this API's primary demo surface is the browser.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Result of a liveness probe."""

    ok: bool = Field(description="True when the service and its database are both reachable.")
    db: str = Field(description="Database status: 'connected' or 'error: <detail>'.")

    model_config = ConfigDict(json_schema_extra={"example": {"ok": True, "db": "connected"}})


class JobAccepted(BaseModel):
    """Returned by any endpoint that starts background work.

    The job is accepted, not finished. Poll `poll_url` for its outcome.
    """

    job_id: uuid.UUID = Field(description="Identifier of the newly created job.")
    status: str = Field(description="Status at creation time, always 'pending'.")
    poll_url: str = Field(description="GET this to follow the job to completion.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "3f1a7c9e-2b4d-4e8a-9c1f-7d2e5a8b0c31",
                "status": "pending",
                "poll_url": "/admin/jobs/3f1a7c9e-2b4d-4e8a-9c1f-7d2e5a8b0c31",
            }
        }
    )


class JobRead(BaseModel):
    """A background job's current state."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3f1a7c9e-2b4d-4e8a-9c1f-7d2e5a8b0c31",
                "kind": "seed",
                "status": "succeeded",
                "detail": "done",
                "result": {"pokemon": 1025, "move": 937, "type_chart": 324},
                "error": None,
                "created_at": "2026-08-29T13:30:00Z",
                "started_at": "2026-08-29T13:30:00Z",
                "finished_at": "2026-08-29T13:30:12Z",
            }
        },
    )

    id: uuid.UUID
    kind: str = Field(description="What kind of work this job performs, e.g. 'seed'.")
    status: str = Field(description="pending, running, succeeded, or failed.")
    detail: str | None = Field(default=None, description="Current phase while running.")
    result: dict[str, Any] | None = Field(default=None, description="Row counts on success.")
    error: str | None = Field(default=None, description="Failure text, if the job failed.")
    created_at: datetime.datetime
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None


class DataQuality(BaseModel):
    """Checks that catch a seed which technically succeeded but is unusable.

    A null sprite or type1 breaks the catalog grid, and it is far cheaper to
    notice here than to notice it as a blank tile during a demo.
    """

    pokemon_missing_sprite_or_type: int = Field(
        description="Pokemon with a null sprite_url or type1. Anything above 0 breaks the grid."
    )
    pokemon_missing_raw: int = Field(
        description="Pokemon with a null raw payload. The column is NOT NULL, so this "
        "is a guard against schema drift rather than a condition that can fire today."
    )
    ok: bool = Field(description="True when every check above is zero.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_missing_sprite_or_type": 0,
                "pokemon_missing_raw": 0,
                "ok": True,
            }
        }
    )


class TypeName(enum.StrEnum):
    """The 18 battle types, as a dropdown rather than a free-text field.

    Spelled out rather than generated so the members are visible to type
    checkers; a test asserts it stays identical to CANONICAL_TYPES.
    """

    normal = "normal"
    fighting = "fighting"
    flying = "flying"
    poison = "poison"
    ground = "ground"
    rock = "rock"
    bug = "bug"
    ghost = "ghost"
    steel = "steel"
    fire = "fire"
    water = "water"
    grass = "grass"
    electric = "electric"
    psychic = "psychic"
    ice = "ice"
    dragon = "dragon"
    dark = "dark"
    fairy = "fairy"


class DeriveTypesResponse(BaseModel):
    """Summary of writing the effectiveness matrix."""

    source: str = Field(description="Where the type payloads were read from.")
    rows_written: int = Field(description="Always 324 on success: 18 attacking x 18 defending.")
    multiplier_distribution: dict[str, int] = Field(
        description="How many pairings landed on each multiplier."
    )
    all_values_legal: bool = Field(description="True when every value is one of 0, 0.5, 1, 2.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source": "fixture",
                "rows_written": 324,
                "multiplier_distribution": {"0": 10, "0.5": 61, "1": 197, "2": 56},
                "all_values_legal": True,
            }
        }
    )


class MatchupResponse(BaseModel):
    """How one attacking type fares against one Pokemon."""

    pokemon_id: int
    pokemon_name: str
    attacking_type: str
    multiplier: float = Field(description="The two components multiplied together.")
    type1_component: float = Field(description="Effectiveness against the primary type.")
    type2_component: float | None = Field(
        default=None, description="Against the secondary type, or null if single-typed."
    )
    explanation: str = Field(description="The derivation, written out.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_id": 6,
                "pokemon_name": "charizard",
                "attacking_type": "rock",
                "multiplier": 4.0,
                "type1_component": 2.0,
                "type2_component": 2.0,
                "explanation": "rock vs fire/flying = 2 * 2 = 4",
            }
        }
    )


class VectorResponse(BaseModel):
    """A Pokemon's full defensive profile."""

    pokemon_id: int
    pokemon_name: str
    types: list[str]
    multipliers: dict[str, float] = Field(
        description="All 18 attacking types mapped to how much damage is taken."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_id": 6,
                "pokemon_name": "charizard",
                "types": ["fire", "flying"],
                "multipliers": {
                    "rock": 4.0,
                    "water": 2.0,
                    "electric": 2.0,
                    "grass": 0.25,
                    "bug": 0.25,
                    "ground": 0.0,
                },
            }
        }
    )


class CacheRebuildResponse(BaseModel):
    """Timing for a derived-layer rebuild."""

    pokemon_count: int
    type_chart_entries: int = Field(description="Entries in the nested chart, 324 when complete.")
    vector_shape: list[int] = Field(description="Shape of the defensive matrix: [pokemon, 18].")
    build_ms: float = Field(description="Time spent computing the derived structures.")
    total_ms: float = Field(description="Wall clock for the whole request, including the lock.")
    built_at: datetime.datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_count": 1025,
                "type_chart_entries": 324,
                "vector_shape": [1025, 18],
                "build_ms": 41.2,
                "total_ms": 42.8,
                "built_at": "2026-08-29T14:00:00Z",
            }
        }
    )


class TypeChartHealth(BaseModel):
    """Whether the stored effectiveness matrix is complete and sane."""

    rows: int
    expected_rows: int = Field(description="18 attacking types x 18 defending types.")
    complete: bool = Field(description="True when every pairing is present.")
    multiplier_distribution: dict[str, int]
    all_values_legal: bool = Field(
        description="False means a multiplier outside 0, 0.5, 1, 2 was stored, which "
        "would make every downstream damage calculation quietly wrong."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "rows": 324,
                "expected_rows": 324,
                "complete": True,
                "multiplier_distribution": {"0": 10, "0.5": 61, "1": 197, "2": 56},
                "all_values_legal": True,
            }
        }
    )


class DerivedCacheHealth(BaseModel):
    """State of the in-memory derived layer."""

    built: bool
    pokemon_count: int
    built_at: datetime.datetime | None = None
    build_ms: float | None = None
    illegal_vector_values: int = Field(
        description="Defensive multipliers outside the six values dual typing can produce."
    )
    chart_complete: bool = Field(
        default=False,
        description="Whether the cached chart was fully loaded rather than defaulted to 1.0.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "built": True,
                "pokemon_count": 1025,
                "built_at": "2026-08-29T14:00:00Z",
                "build_ms": 41.2,
                "illegal_vector_values": 0,
                "chart_complete": True,
            }
        }
    )


class StatsResponse(BaseModel):
    """One call covering the health of the data and the derived layer.

    Row counts show a seed working; the type chart and derived sections show
    whether the effectiveness maths behind every later feature is sound.
    """

    counts: dict[str, int] = Field(description="Row count per table, read live.")
    data_quality: DataQuality
    type_chart: TypeChartHealth
    derived: DerivedCacheHealth

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "counts": {
                    "pokemon": 1025,
                    "move": 937,
                    "pokemon_move": 79120,
                    "pokemon_ability": 2411,
                    "type_chart": 324,
                    "app_user": 0,
                    "team": 0,
                    "team_member": 0,
                    "sync_run": 0,
                    "data_change": 0,
                    "change_ack": 0,
                    "job": 1,
                },
                "data_quality": {
                    "pokemon_missing_sprite_or_type": 0,
                    "pokemon_missing_raw": 0,
                    "ok": True,
                },
                "type_chart": {
                    "rows": 324,
                    "expected_rows": 324,
                    "complete": True,
                    "multiplier_distribution": {"0": 10, "0.5": 61, "1": 197, "2": 56},
                    "all_values_legal": True,
                },
                "derived": {
                    "built": True,
                    "pokemon_count": 1025,
                    "built_at": "2026-08-29T14:00:00Z",
                    "build_ms": 41.2,
                    "illegal_vector_values": 0,
                },
            }
        }
    )


class NormalizeDebugResponse(BaseModel):
    """A raw payload and its projection, side by side."""

    pokemon_id: int
    pokemon_name: str
    raw_field_count: int = Field(description="Top-level keys in the stored payload.")
    normalized_field_count: int = Field(description="Keys surviving the projection.")
    dropped_fields: list[str] = Field(
        description="Top-level keys discarded as unconsumed. Changes to these "
        "must never appear in the change feed."
    )
    normalized: dict[str, Any] = Field(description="The projection that is hashed and diffed.")
    section_hashes: dict[str, str] = Field(description="Recomputed from the payload right now.")
    stored_hashes: dict[str, str] = Field(description="What the database holds.")
    hashes_match: bool = Field(
        description="False means the stored hash disagrees with a fresh computation, "
        "which would make every sync report this Pokemon as changed."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_id": 6,
                "pokemon_name": "charizard",
                "raw_field_count": 14,
                "normalized_field_count": 10,
                "dropped_fields": ["base_experience", "order", "species"],
                "normalized": {
                    "id": 6,
                    "name": "charizard",
                    "types": ["fire", "flying"],
                    "stats": {"attack": 84, "hp": 78},
                    "moves": [10, 19, 53],
                    "sprite": "https://img/6.png",
                },
                "section_hashes": {"stats_hash": "6b86b273...", "types_hash": "d4735e3a..."},
                "stored_hashes": {"stats_hash": "6b86b273...", "types_hash": "d4735e3a..."},
                "hashes_match": True,
            }
        }
    )


class DeterminismMismatch(BaseModel):
    """One stored hash that disagrees with a fresh computation."""

    pokemon_id: int
    pokemon_name: str
    section: str
    stored_hash: str
    recomputed_hash: str


class DeterminismCheckResponse(BaseModel):
    """Result of re-hashing every stored Pokemon.

    This is the check that protects the whole change-detection demo. If
    normalisation is not deterministic, the next sync reports every Pokemon as
    changed and the feed becomes noise.
    """

    checked: int = Field(description="Pokemon re-normalised and re-hashed.")
    sections_checked: int = Field(description="Individual hashes compared.")
    mismatches: int = Field(description="Hashes that disagreed. Anything above 0 is a bug.")
    mismatch_samples: list[DeterminismMismatch] = Field(
        description="Up to 10 examples, for diagnosis."
    )
    duration_ms: float
    ok: bool = Field(description="True when nothing mismatched.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "checked": 1025,
                "sections_checked": 4100,
                "mismatches": 0,
                "mismatch_samples": [],
                "duration_ms": 412.5,
                "ok": True,
            }
        }
    )


# --- Shared -----------------------------------------------------------------


class ErrorResponse(BaseModel):
    """The single error shape for every router.

    Matches FastAPI's own HTTPException body so handlers and framework errors
    are indistinguishable to a client.
    """

    detail: str = Field(description="Human-readable explanation of the failure.")

    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Team not found"}})


class PokemonStats(BaseModel):
    """The six base stats, exactly as PokeAPI reports them.

    Base values, not level-50 values: the conversion belongs to the derived
    layer so change detection keeps comparing like with like.
    """

    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "hp": 78,
                "attack": 84,
                "defense": 78,
                "special_attack": 109,
                "special_defense": 85,
                "speed": 100,
            }
        }
    )


class PokemonSummary(BaseModel):
    """A catalog entry. Never includes the raw payload column."""

    id: int
    name: str
    sprite_url: str | None
    types: list[str] = Field(description="One or two types, in slot order.")
    stats: PokemonStats

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 6,
                "name": "charizard",
                "sprite_url": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/6.png",
                "types": ["fire", "flying"],
                "stats": {
                    "hp": 78,
                    "attack": 84,
                    "defense": 78,
                    "special_attack": 109,
                    "special_defense": 85,
                    "speed": 100,
                },
            }
        }
    )


class MoveSummary(BaseModel):
    """One move a Pokemon can learn."""

    id: int
    name: str
    type: str
    damage_class: str = Field(description="physical, special, or status.")
    power: int | None = Field(default=None, description="Null for status moves.")
    accuracy: int | None = Field(default=None, description="Null for moves that never miss.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 53,
                "name": "flamethrower",
                "type": "fire",
                "damage_class": "special",
                "power": 90,
                "accuracy": 100,
            }
        }
    )


class PokemonDetail(PokemonSummary):
    """A catalog entry plus its movepool."""

    moves: list[MoveSummary]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 6,
                "name": "charizard",
                "sprite_url": "https://img/6.png",
                "types": ["fire", "flying"],
                "stats": {
                    "hp": 78,
                    "attack": 84,
                    "defense": 78,
                    "special_attack": 109,
                    "special_defense": 85,
                    "speed": 100,
                },
                "moves": [
                    {
                        "id": 53,
                        "name": "flamethrower",
                        "type": "fire",
                        "damage_class": "special",
                        "power": 90,
                        "accuracy": 100,
                    }
                ],
            }
        }
    )


class PokemonPage(BaseModel):
    """One page of catalog results.

    Cursor-based rather than offset: the frontend scrolls infinitely, and an
    OFFSET grows more expensive the further down you go while also skipping or
    repeating rows if the underlying data shifts mid-scroll.
    """

    items: list[PokemonSummary]
    next_cursor: str | None = Field(
        default=None, description="Pass back as `cursor`. Null on the last page."
    )
    has_more: bool

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [],
                "next_cursor": "eyJrIjoiNiIsImkiOjZ9",
                "has_more": True,
            }
        }
    )


# --- Teams ------------------------------------------------------------------


class TeamMemberRead(BaseModel):
    """One roster slot, resolved to the Pokemon occupying it."""

    slot: int = Field(description="1 through 6.")
    pokemon_id: int
    name: str
    sprite_url: str | None
    types: list[str]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "slot": 1,
                "pokemon_id": 25,
                "name": "pikachu",
                "sprite_url": "https://img/25.png",
                "types": ["electric"],
            }
        }
    )


class TeamRead(BaseModel):
    """A team and its roster, ordered by slot."""

    id: int
    name: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    members: list[TeamMemberRead]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "name": "Kanto classics",
                "created_at": "2026-08-29T12:00:00Z",
                "updated_at": "2026-08-29T12:30:00Z",
                "members": [
                    {
                        "slot": 1,
                        "pokemon_id": 25,
                        "name": "pikachu",
                        "sprite_url": "https://img/25.png",
                        "types": ["electric"],
                    }
                ],
            }
        }
    )


class TeamCreate(BaseModel):
    """Payload for creating a team."""

    name: str = Field(min_length=1, max_length=100)

    model_config = ConfigDict(json_schema_extra={"example": {"name": "Kanto classics"}})


class TeamUpdate(BaseModel):
    """Payload for renaming a team."""

    name: str = Field(min_length=1, max_length=100)

    model_config = ConfigDict(json_schema_extra={"example": {"name": "Kanto classics v2"}})


class RosterUpdate(BaseModel):
    """The complete ordered roster.

    Drag-and-drop produces a whole new ordering, so the client sends the entire
    array and the server replaces every row in one transaction. Incremental
    add/remove/move endpoints would need three round trips to express one drag
    and could interleave into an inconsistent order.
    """

    pokemon_ids: list[int] = Field(
        description="Ordered Pokemon ids. Position determines slot. At most 6, no duplicates.",
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"pokemon_ids": [25, 6, 9, 3, 143, 150]}}
    )


# --- Counter-team -----------------------------------------------------------


class CounterTeamRequest(BaseModel):
    """The enemy team to answer."""

    pokemon_ids: list[int] = Field(description="The opposing team, up to 6 Pokemon.")

    model_config = ConfigDict(
        json_schema_extra={
            # Charizard, Venusaur, Blastoise, Gengar, Skarmory, Tyranitar.
            # Pre-filled so "Try it out" gives a meaningful answer in one click.
            "example": {"pokemon_ids": [6, 3, 9, 94, 227, 248]}
        }
    )


class CounterAnswer(BaseModel):
    """How well one pick answers one enemy.

    Phase 9 adds move, turns-to-KO, and speed fields here without changing the
    surrounding shape.
    """

    enemy_id: int
    enemy_name: str
    multiplier: float = Field(
        description="The matchup score: offensive multiplier divided by the "
        "worst multiplier the enemy lands back. Higher is better."
    )
    rationale: str = Field(description="How the score was arrived at.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enemy_id": 6,
                "enemy_name": "charizard",
                "multiplier": 4.0,
                "rationale": "rock hits fire/flying for 4x; takes 1x back",
            }
        }
    )


class CounterPick(BaseModel):
    """One recommended Pokemon and what it answers."""

    id: int
    name: str
    sprite_url: str | None
    types: list[str]
    answers: list[CounterAnswer]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 248,
                "name": "tyranitar",
                "sprite_url": "https://img/248.png",
                "types": ["rock", "dark"],
                "answers": [
                    {
                        "enemy_id": 6,
                        "enemy_name": "charizard",
                        "multiplier": 4.0,
                        "rationale": "rock hits fire/flying for 4x; takes 1x back",
                    }
                ],
            }
        }
    )


class CoverageEntry(BaseModel):
    """The best answer the recommended team has for one enemy."""

    enemy_id: int
    enemy_name: str
    best_answer: str = Field(description="Name of the pick that answers this enemy best.")
    best_answer_id: int
    score: float

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enemy_id": 6,
                "enemy_name": "charizard",
                "best_answer": "tyranitar",
                "best_answer_id": 248,
                "score": 4.0,
            }
        }
    )


class CounterTeamResponse(BaseModel):
    """Six picks and the coverage they provide.

    Type effectiveness only in this version: no damage formula, no stats, no
    moves, no speed. Phase 9 replaces the scoring function behind this shape.
    """

    picks: list[CounterPick]
    coverage: list[CoverageEntry]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "picks": [],
                "coverage": [
                    {
                        "enemy_id": 6,
                        "enemy_name": "charizard",
                        "best_answer": "tyranitar",
                        "best_answer_id": 248,
                        "score": 4.0,
                    }
                ],
            }
        }
    )


class ExplainResponse(BaseModel):
    """A query and the plan Postgres chose for it."""

    query: str = Field(description="Which named query was explained.")
    sql: str
    plan: list[str] = Field(description="EXPLAIN (ANALYZE, BUFFERS) output, line by line.")
    uses_index: bool = Field(
        description="True when the plan mentions an index scan. A sequential scan "
        "here means an index that was supposed to serve this query is not being used."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "name_search",
                "sql": "SELECT id, name FROM pokemon WHERE name LIKE 'char%' ORDER BY id LIMIT 49",
                "plan": [
                    "Bitmap Heap Scan on pokemon (actual time=0.02..0.03 rows=6 loops=1)",
                    "  ->  Bitmap Index Scan on ix_pokemon_name_prefix",
                ],
                "uses_index": True,
            }
        }
    )
