"""Pydantic response schemas. Routes never return ORM objects directly."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Result of a liveness probe."""

    ok: bool = Field(description="True when the service and its database are both reachable.")
    db: str = Field(description="Database status: 'connected' or 'error: <detail>'.")
