"""Alerts: upstream changes affecting the caller's teams."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.dependencies import CurrentUser, SessionDep
from api.schemas import AlertsResponse, DismissResponse, error_response
from api.services import alerts as alert_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get(
    "",
    response_model=AlertsResponse,
    summary="Changes affecting your teams",
    description=(
        f"Changes detected in the last {alert_service.WINDOW_DAYS} days to Pokemon on "
        "your teams, excluding ones you have dismissed.\n\n"
        "### An empty feed usually means one of two things\n\n"
        "**No sync has run yet.** `POST /admin/simulate-change` diverges our stored "
        "snapshot; it does not write change records. Those come from "
        "`POST /admin/sync`, which compares that snapshot against upstream. Check "
        "`GET /admin/changes`: if it is empty, the sync is the missing step.\n\n"
        "**The `X-User-Id` header was omitted.** It is optional, and leaving it out "
        "mints a brand-new identity per request -- one that owns no teams and so "
        "sees no alerts. Send the same UUID you created your teams with.\n\n"
        "Full sequence: create a team, `POST /admin/simulate-change`, "
        "`POST /admin/sync`, then this endpoint with the same `X-User-Id`.\n\n"
        "Grouped by Pokemon, with the teams each one appears in, and described as "
        "sentences rather than raw diffs. A Pokemon on three of your teams produces "
        "one group listing all three, not three copies.\n\n"
        "Dismissals are per user: dismissing an alert silences it for you and nobody "
        "else. Older changes are not deleted, they simply stop being news -- see "
        "`GET /admin/changes` for the full history.\n\n"
        "To see the window work without waiting a week, backdate a change with "
        "`POST /admin/age-change/{change_id}?days=8` and watch it leave this feed."
    ),
)
async def list_alerts(session: SessionDep, user: CurrentUser) -> AlertsResponse:
    return await alert_service.list_alerts(session, user.id)


@router.post(
    "/{change_id}/dismiss",
    response_model=DismissResponse,
    summary="Dismiss one alert",
    description=(
        "Acknowledges a change so it stops appearing in your feed.\n\n"
        "Idempotent: dismissing something already dismissed answers 200 with the "
        "original timestamp and `already_dismissed: true`, rather than failing on "
        "the composite key. A client retrying a request it already made has not "
        "done anything wrong."
    ),
    responses={404: error_response("No change with that id.", "Change not found")},
)
async def dismiss_alert(change_id: int, session: SessionDep, user: CurrentUser) -> DismissResponse:
    result = await alert_service.dismiss(session, user.id, change_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")
    return result
