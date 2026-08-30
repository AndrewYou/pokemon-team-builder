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

    Deliberately carries no model-level example. One model documents every
    failure on every route, so an example here would be shown for all of them:
    a "Team not found" example would appear under a 401 on /admin/sync.
    Examples belong on the individual responses, via `error_response` below.
    """

    detail: str = Field(description="Human-readable explanation of the failure.")


def error_response(description: str, detail: str) -> dict[str, Any]:
    """Declare one error response with the message that route actually raises.

    Keeps the example next to the code that produces it, so Swagger shows the
    real string rather than one borrowed from an unrelated endpoint.
    """
    return {
        "model": ErrorResponse,
        "description": description,
        "content": {"application/json": {"example": {"detail": detail}}},
    }


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
        description="The matchup score in [0, 1]: how much of the exchange this "
        "pick wins, from the damage it deals against the damage it takes."
    )
    rationale: str = Field(description="How the score was arrived at.")
    # Added by the damage model. The shape is unchanged: these are new fields
    # inside the objects the frontend already renders.
    move_name: str = Field(default="", description="The move chosen against this enemy.")
    damage_class: str = Field(default="", description="physical or special.")
    damage_fraction: float = Field(
        default=0.0, description="Share of the enemy's health removed per turn."
    )
    turns_to_ko: int = Field(
        default=0, description="Rounded for display only; scoring uses the fraction."
    )
    outspeeds: bool = Field(default=False, description="Whether this pick moves first.")
    # Turn margin: the number a person can actually read. Selection and sorting
    # still use `multiplier`; these are derived for display.
    our_turns: int | None = Field(
        default=None, description="Turns we need to KO. Null when we never can."
    )
    their_turns: int | None = Field(
        default=None,
        description="Turns they need to KO us, after the one they lose to our speed. "
        "Null when they never can.",
    )
    margin: int | None = Field(
        default=None,
        description="their_turns minus our_turns. Positive means we win the 1v1 with "
        "that many turns to spare. Null when either side can never KO the other.",
    )
    verdict: str = Field(
        default="", description="Dominates, Wins, Trades, or Loses, from the margin."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enemy_id": 6,
                "enemy_name": "charizard",
                "multiplier": 0.79,
                "rationale": "stone-edge (rock) takes 96% per turn, 2 to KO; takes 25% back",
                "move_name": "stone-edge",
                "damage_class": "physical",
                "damage_fraction": 0.96,
                "turns_to_ko": 2,
                "outspeeds": False,
                "our_turns": 2,
                "their_turns": 5,
                "margin": 3,
                "verdict": "Dominates",
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
                        "multiplier": 0.79,
                        "rationale": "stone-edge (rock) takes 96% per turn, 2 to KO",
                        "move_name": "stone-edge",
                        "damage_class": "physical",
                        "damage_fraction": 0.96,
                        "turns_to_ko": 2,
                        "outspeeds": False,
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

    size: int = Field(
        description="Number of picks, always equal to the number of Pokemon submitted."
    )
    picks: list[CounterPick]
    coverage: list[CoverageEntry]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "size": 1,
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


# --- Sync -------------------------------------------------------------------


class SyncRunRead(BaseModel):
    """One execution of the change-detection job.

    A run that scanned every record and found nothing is as important as one
    that found something: it is the evidence the detector is not inventing
    changes.
    """

    id: int
    source: str = Field(description="live, fixture, or stale.")
    status: str
    records_scanned: int
    changes_found: int
    started_at: datetime.datetime
    finished_at: datetime.datetime | None = None
    duration_ms: float | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "summary": "A run that found nothing",
                    "description": (
                        "Every record checked, no divergence. This is the normal "
                        "outcome and the proof the detector is not noisy."
                    ),
                    "value": {
                        "id": 12,
                        "source": "fixture",
                        "status": "succeeded",
                        "records_scanned": 1025,
                        "changes_found": 0,
                        "started_at": "2026-08-29T14:00:00Z",
                        "finished_at": "2026-08-29T14:00:09Z",
                        "duration_ms": 9120.0,
                    },
                },
                {
                    "summary": "A run that detected changes",
                    "description": "Five discrete field changes across two Pokemon.",
                    "value": {
                        "id": 13,
                        "source": "fixture",
                        "status": "succeeded",
                        "records_scanned": 1025,
                        "changes_found": 5,
                        "started_at": "2026-08-29T14:05:00Z",
                        "finished_at": "2026-08-29T14:05:10Z",
                        "duration_ms": 10230.0,
                    },
                },
            ]
        }
    )


class ChangeRead(BaseModel):
    """One detected field-level change, rendered for a human."""

    id: int
    sync_run_id: int
    entity_type: str
    entity_id: str
    pokemon_name: str | None = None
    field_path: str
    old_value: str | None = Field(description="What our snapshot held before the sync.")
    new_value: str | None = Field(description="What upstream reports now.")
    message: str = Field(description="The alert text a user sees.")
    detected_at: datetime.datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 41,
                "sync_run_id": 13,
                "entity_type": "pokemon",
                "entity_id": "25",
                "pokemon_name": "pikachu",
                "field_path": "stats.attack",
                "old_value": "71",
                "new_value": "55",
                "message": "Pikachu's Attack changed from 71 to 55",
                "detected_at": "2026-08-29T14:05:08Z",
            }
        }
    )


class DriftEntry(BaseModel):
    """A stored row that no longer matches the reference snapshot."""

    pokemon_id: int
    name: str
    sections: list[str] = Field(description="Which section hashes disagree.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"pokemon_id": 25, "name": "pikachu", "sections": ["stats", "types"]}
        }
    )


class DriftResponse(BaseModel):
    """What a sync would find if it ran right now."""

    reference: str = Field(description="What the stored rows were compared against.")
    checked: int
    drifted: int
    entries: list[DriftEntry]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reference": "fixture",
                "checked": 1025,
                "drifted": 2,
                "entries": [
                    {"pokemon_id": 25, "name": "pikachu", "sections": ["stats", "types"]},
                    {"pokemon_id": 6, "name": "charizard", "sections": ["sprite"]},
                ],
            }
        }
    )


class SimulateChangeRequest(BaseModel):
    """Which divergences to introduce. Every field is optional."""

    pokemon_ids: list[int] | None = Field(
        default=None, description="Omit to pick `count` Pokemon at random."
    )
    fields: list[str] | None = Field(
        default=None,
        description=(
            "Any of stats, types, sprite, moves. Omit for one random group per "
            "Pokemon. List several and EVERY listed group is mutated on EVERY "
            "named Pokemon."
        ),
    )
    mutations_per_field: int = Field(
        default=1,
        ge=1,
        description=(
            "Discrete changes within each group, drawn without replacement. "
            "Clamped to the group's maximum (stats 6, types 2, sprite 1, moves 5) "
            "rather than rejected."
        ),
    )
    count: int = Field(default=3, ge=1, le=25, description="Used only when pokemon_ids is omitted.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_ids": [25, 6],
                "fields": ["stats", "types", "sprite"],
                "mutations_per_field": 2,
                "count": 3,
            }
        }
    )


class SimulatedMutation(BaseModel):
    """One discrete divergence, which becomes exactly one data_change row."""

    field_path: str = Field(description="The path the change will appear under.")
    section: str
    upstream_value: Any = Field(description="The true value, which the sync will restore.")
    mutated_to: Any = Field(description="What our snapshot now holds.")
    expect_alert: str = Field(
        description="The exact alert text the next sync should produce, for comparing "
        "against the UI verbatim."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "field_path": "stats.attack",
                "section": "stats",
                "upstream_value": 55,
                "mutated_to": 71,
                "expect_alert": "Pikachu's Attack changed from 71 to 55",
            }
        }
    )


class SimulatedPokemon(BaseModel):
    """Everything done to one Pokemon."""

    pokemon_id: int
    name: str
    sections_touched: list[str]
    mutations: list[SimulatedMutation]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_id": 25,
                "name": "pikachu",
                "sections_touched": ["stats", "types"],
                "mutations": [
                    {
                        "field_path": "stats.attack",
                        "section": "stats",
                        "upstream_value": 55,
                        "mutated_to": 71,
                        "expect_alert": "Pikachu's Attack changed from 71 to 55",
                    }
                ],
            }
        }
    )


class SimulateChangeResponse(BaseModel):
    """What was diverged, and what the next sync should report."""

    total_mutations: int = Field(
        description="Exactly how many data_change rows the next sync must produce."
    )
    affected_pokemon: int
    mutations_per_field_effective: dict[str, int] = Field(
        description="The requested count after clamping to each group's maximum."
    )
    by_pokemon: list[SimulatedPokemon]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_mutations": 10,
                "affected_pokemon": 2,
                "mutations_per_field_effective": {"stats": 2, "types": 2, "sprite": 1},
                "by_pokemon": [],
            }
        }
    )


class ResetDemoDeleted(BaseModel):
    """Rows removed, per table."""

    change_ack: int
    data_change: int
    sync_run: int

    model_config = ConfigDict(
        json_schema_extra={"example": {"change_ack": 0, "data_change": 14, "sync_run": 8}}
    )


class ResetDemoResponse(BaseModel):
    """What the reset cleared, and whether the snapshot was restored."""

    deleted: ResetDemoDeleted
    snapshot_restored: bool = Field(
        description="True when a fixture seed ran, clearing any outstanding drift."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "deleted": {"change_ack": 0, "data_change": 14, "sync_run": 8},
                "snapshot_restored": True,
            }
        }
    )


# --- Alerts -----------------------------------------------------------------


class AffectedTeam(BaseModel):
    """One of the caller's teams containing the changed Pokemon."""

    team_id: int
    team_name: str

    model_config = ConfigDict(
        json_schema_extra={"example": {"team_id": 1, "team_name": "Kanto classics"}}
    )


class AlertChange(BaseModel):
    """One change, described the way a player would say it."""

    change_id: int = Field(description="Pass to /alerts/{change_id}/dismiss.")
    field_path: str
    old_value: str | None = Field(description="What our snapshot held before the sync.")
    new_value: str | None = Field(description="What upstream reports now.")
    message: str = Field(description="The sentence to show. Never a raw diff.")
    detected_at: datetime.datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "change_id": 41,
                "field_path": "stats.attack",
                "old_value": "55",
                "new_value": "60",
                "message": "Pikachu's Attack changed from 55 to 60",
                "detected_at": "2026-08-29T14:05:08Z",
            }
        }
    )


class AlertGroup(BaseModel):
    """Everything that changed about one Pokemon, and where it sits."""

    pokemon_id: int
    pokemon_name: str
    sprite_url: str | None
    affected_teams: list[AffectedTeam] = Field(
        description="Which of your teams contain this Pokemon."
    )
    changes: list[AlertChange]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pokemon_id": 25,
                "pokemon_name": "pikachu",
                "sprite_url": "https://img/25.png",
                "affected_teams": [
                    {"team_id": 1, "team_name": "Kanto classics"},
                    {"team_id": 4, "team_name": "Speed run"},
                ],
                "changes": [
                    {
                        "change_id": 41,
                        "field_path": "stats.attack",
                        "old_value": "55",
                        "new_value": "60",
                        "message": "Pikachu's Attack changed from 55 to 60",
                        "detected_at": "2026-08-29T14:05:08Z",
                    },
                    {
                        "change_id": 42,
                        "field_path": "types[0]",
                        "old_value": "electric",
                        "new_value": "ghost",
                        "message": "Pikachu's primary type changed from electric to ghost",
                        "detected_at": "2026-08-29T14:05:08Z",
                    },
                ],
            }
        }
    )


class AlertsResponse(BaseModel):
    """Undismissed changes affecting the caller's teams, grouped by Pokemon."""

    window_days: int = Field(description="How far back the feed looks.")
    total_changes: int
    affected_pokemon: int
    groups: list[AlertGroup]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "window_days": 7,
                "total_changes": 2,
                "affected_pokemon": 1,
                "groups": [
                    {
                        "pokemon_id": 25,
                        "pokemon_name": "pikachu",
                        "sprite_url": "https://img/25.png",
                        "affected_teams": [{"team_id": 1, "team_name": "Kanto classics"}],
                        "changes": [
                            {
                                "change_id": 41,
                                "field_path": "stats.attack",
                                "old_value": "55",
                                "new_value": "60",
                                "message": "Pikachu's Attack changed from 55 to 60",
                                "detected_at": "2026-08-29T14:05:08Z",
                            }
                        ],
                    }
                ],
            }
        }
    )


class DismissResponse(BaseModel):
    """Result of dismissing one change."""

    change_id: int
    acknowledged_at: datetime.datetime
    already_dismissed: bool = Field(
        description="True when it was already dismissed. Re-dismissing is a 200, not an error."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "change_id": 41,
                "acknowledged_at": "2026-08-29T14:10:00Z",
                "already_dismissed": False,
            }
        }
    )


class DismissAllResponse(BaseModel):
    """Result of clearing the whole feed."""

    dismissed: int = Field(
        description="Changes newly acknowledged. Zero when there was nothing left."
    )

    model_config = ConfigDict(json_schema_extra={"example": {"dismissed": 7}})


class AgedChangeResponse(BaseModel):
    """Result of backdating a change, so the alert window is demonstrable."""

    change_id: int
    days: int
    detected_at_before: datetime.datetime
    detected_at_after: datetime.datetime
    still_in_window: bool = Field(
        description="False once the change has been aged out of the 7-day feed."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "change_id": 41,
                "days": 8,
                "detected_at_before": "2026-08-29T14:05:08Z",
                "detected_at_after": "2026-08-21T14:05:08Z",
                "still_in_window": False,
            }
        }
    )


class MatchupDetail(BaseModel):
    """Every number behind one attacker-versus-defender pairing."""

    attacker_id: int
    attacker_name: str
    attacker_types: list[str]
    defender_id: int
    defender_name: str
    defender_types: list[str]

    move_name: str
    move_type: str
    damage_class: str
    move_power: int
    move_accuracy: int | None

    attack_stat: int = Field(description="Attack or Special Attack, at level 50.")
    defense_stat: int = Field(description="Defense or Special Defense, at level 50.")
    defender_hp: int
    stab: float
    type_multiplier: float

    raw_damage: float
    damage_fraction: float = Field(description="What the scorer uses. Continuous.")
    turns_to_ko: int = Field(description="Rounded, for display only.")

    attacker_speed: int
    defender_speed: int
    outspeeds: bool

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "attacker_id": 6,
                "attacker_name": "charizard",
                "attacker_types": ["fire", "flying"],
                "defender_id": 9,
                "defender_name": "blastoise",
                "defender_types": ["water"],
                "move_name": "wing-attack",
                "move_type": "flying",
                "damage_class": "physical",
                "move_power": 60,
                "move_accuracy": 100,
                "attack_stat": 89,
                "defense_stat": 105,
                "defender_hp": 139,
                "stab": 1.5,
                "type_multiplier": 1.0,
                "raw_damage": 25.8,
                "damage_fraction": 0.1856,
                "turns_to_ko": 6,
                "attacker_speed": 105,
                "defender_speed": 83,
                "outspeeds": True,
            }
        }
    )
