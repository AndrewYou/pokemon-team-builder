"""Triggering the change-detection sync.

Separate from the rest of the admin router because this is the one operation a
scheduled job needs to call, and it therefore accepts a second kind of
credential.
"""

from __future__ import annotations

import enum
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from api.dependencies import SessionDep
from api.models import JobKind
from api.schemas import ErrorResponse, JobAccepted
from api.security import verify_admin_or_cron
from api.services import jobs as job_service
from api.services import sync_service

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_or_cron)],
    responses={401: {"model": ErrorResponse, "description": "No valid credential."}},
)


class SyncSourceOption(enum.StrEnum):
    """Where the sync reads its comparison data from.

    Rendered as a dropdown so a demo cannot fat-finger the source.
    """

    fixture = "fixture"
    live = "live"
    # Replays our own stored snapshot, so a run against it must find zero
    # changes. The cheapest demonstration that the detector is not noisy.
    stale = "stale"


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
    summary="Run change detection",
    description=(
        "Compares upstream against our stored snapshot, records every field-level "
        "difference, and updates the snapshot.\\n\\n"
        "Accepts **either** HTTP Basic (a human in this page) **or** an "
        "`X-Cron-Secret` header (a scheduled job). A scheduled caller cannot answer "
        "a browser password prompt, and a reviewer should not need a shared secret.\\n\\n"
        "Returns 202 immediately and runs in the background: a live sync issues "
        "thousands of requests and would otherwise hang this page. Poll `poll_url` "
        "for progress, and see `GET /sync-runs` for the history.\\n\\n"
        "`stale` replays our own stored data as if it were upstream, which must "
        "find exactly zero changes.\\n\\n"
        "Returns 409 if a sync is already running."
    ),
    responses={409: {"model": ErrorResponse, "description": "A sync is already running."}},
)
async def start_sync(
    background: BackgroundTasks,
    session: SessionDep,
    source: Annotated[
        SyncSourceOption, Query(description="Where to read comparison data from.")
    ] = SyncSourceOption.fixture,
) -> JobAccepted:
    try:
        job = await job_service.create_job(session, JobKind.sync)
    except job_service.JobAlreadyRunning as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    background.add_task(sync_service.run_sync_job, job.id, source.value)
    return JobAccepted(job_id=job.id, status=job.status.value, poll_url=f"/admin/jobs/{job.id}")
