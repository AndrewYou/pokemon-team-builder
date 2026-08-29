"""Pydantic request/response schemas.

Routes never return ORM objects directly. Every model carries a realistic
example so that Swagger's "Try it out" pre-fills with a working payload rather
than an empty skeleton -- this API's primary demo surface is the browser.
"""

from __future__ import annotations

import datetime
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


class StatsResponse(BaseModel):
    """Live row counts, so re-running one request shows the database filling up."""

    counts: dict[str, int] = Field(description="Row count per table, read live.")
    data_quality: DataQuality

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
            }
        }
    )
