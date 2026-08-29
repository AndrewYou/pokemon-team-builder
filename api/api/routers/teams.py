"""Team management. Thin: parse, delegate, return."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.dependencies import CurrentUser, SessionDep
from api.models import Team
from api.schemas import RosterUpdate, TeamCreate, TeamRead, TeamUpdate, error_response
from api.services import teams as team_service

router = APIRouter(prefix="/teams", tags=["teams"])

# Declared per route rather than on the router: list and create take no id, so
# documenting a 404 on them would describe a response they cannot produce.
TEAM_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: error_response(
        "No such team for this user. Another user's team is also 404, never 403, "
        "since a 403 would confirm the id exists.",
        "Team not found",
    )
}


async def _owned_team(session: SessionDep, user: CurrentUser, team_id: int) -> Team:
    """Fetch a team or 404.

    404 rather than 403 for a team belonging to someone else: a 403 would
    confirm the id exists, which is information the caller has no claim to.
    """
    team = await team_service.get_team(session, user.id, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


@router.get(
    "",
    response_model=list[TeamRead],
    summary="List your teams",
    description="Every team belonging to the caller, newest first, with rosters ordered by slot.",
)
async def list_teams(session: SessionDep, user: CurrentUser) -> list[TeamRead]:
    return await team_service.list_teams(session, user.id)


@router.post(
    "",
    response_model=TeamRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
    description="Creates an empty team. Add Pokemon with PUT /teams/{id}/members.",
)
async def create_team(payload: TeamCreate, session: SessionDep, user: CurrentUser) -> TeamRead:
    return await team_service.create_team(session, user.id, payload.name)


@router.get(
    "/{team_id}",
    response_model=TeamRead,
    summary="Get one team",
    description="Members are returned ordered by slot.",
    responses=TEAM_NOT_FOUND,
)
async def get_team(team_id: int, session: SessionDep, user: CurrentUser) -> TeamRead:
    team = await _owned_team(session, user, team_id)
    return await team_service.to_read(session, team)


@router.patch(
    "/{team_id}",
    response_model=TeamRead,
    summary="Rename a team",
    description="Only the name is editable here; the roster has its own endpoint.",
    responses=TEAM_NOT_FOUND,
)
async def rename_team(
    team_id: int, payload: TeamUpdate, session: SessionDep, user: CurrentUser
) -> TeamRead:
    team = await _owned_team(session, user, team_id)
    return await team_service.rename_team(session, team, payload.name)


@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a team",
    description="Roster rows are removed with it by ON DELETE CASCADE.",
    responses=TEAM_NOT_FOUND,
)
async def delete_team(team_id: int, session: SessionDep, user: CurrentUser) -> None:
    team = await _owned_team(session, user, team_id)
    await team_service.delete_team(session, team)


@router.put(
    "/{team_id}/members",
    response_model=TeamRead,
    summary="Replace the roster",
    description=(
        "Takes the complete ordered list of Pokemon ids and replaces every slot "
        "in one transaction. Position in the array becomes the slot number.\\n\\n"
        "There are deliberately no add, remove, or move endpoints: a drag-and-drop "
        "reorder produces a whole new ordering, so sending the entire array is both "
        "simpler and atomic.\\n\\n"
        "Rejects rosters over 6, duplicate Pokemon, and unknown ids with 422."
    ),
    responses={
        **TEAM_NOT_FOUND,
        422: error_response(
            "Roster rejected: too many members, duplicates, or an unknown id.",
            "A team holds at most 6 Pokemon; received 7.",
        ),
    },
)
async def replace_roster(
    team_id: int, payload: RosterUpdate, session: SessionDep, user: CurrentUser
) -> TeamRead:
    team = await _owned_team(session, user, team_id)
    try:
        return await team_service.replace_roster(session, team, payload.pokemon_ids)
    except team_service.RosterError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
