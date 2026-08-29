"""Public sync history.

Deliberately unauthenticated. The run log is the evidence that change detection
works, and a reviewer should be able to read it without credentials -- including
the runs that found nothing, which are the ones that prove the detector is not
simply inventing notifications.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from api.dependencies import SessionDep
from api.schemas import SyncRunRead
from api.services import sync_service

router = APIRouter(tags=["alerts"])


@router.get(
    "/sync-runs",
    response_model=list[SyncRunRead],
    summary="Change-detection run history",
    description=(
        "Every sync, newest first, with what it scanned and what it found.\\n\\n"
        "A run reporting 1025 records scanned and 0 changes found is the point of "
        "this log: it shows the detector checked everything and reported nothing, "
        "which is what distinguishes it from a random notification generator."
    ),
)
async def list_sync_runs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SyncRunRead]:
    return await sync_service.list_sync_runs(session, limit)
