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
