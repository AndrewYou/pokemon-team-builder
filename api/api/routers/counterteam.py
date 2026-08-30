"""Counter-team recommendations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.counterteam.scoring import MAX_TEAM_SIZE
from api.derived import registry
from api.routers.admin import require_cache
from api.schemas import CounterTeamRequest, CounterTeamResponse, error_response
from api.services import counterteam as counter_service

router = APIRouter(prefix="/counter-team", tags=["counter-team"])


@router.post(
    "",
    response_model=CounterTeamResponse,
    summary="Suggest a team that counters this one",
    description=(
        "Takes 1 to 6 Pokemon ids and returns **the same number** of picks, each "
        "with a per-enemy breakdown, plus a coverage summary.\n\n"
        "The count is derived from the request rather than configured: a team of "
        "three is answered by three."
        "\n\n"
        "**Type effectiveness only.** No damage formula, no stats, no moves, no "
        "speed. `offense` is the best multiplier a pick's own types land on the "
        "enemy, `defense` is the inverse of the worst multiplier it takes back, "
        "and the score is their product.\n\n"
        "Picks are chosen by marginal gain over six rounds: each round takes the "
        "candidate that most improves the current worst-covered enemies, so "
        "diminishing returns come from the structure rather than a decay factor.\n\n"
        "Stateless -- nothing is stored, and the whole computation runs off the "
        "in-memory derived cache."
    ),
    responses={
        422: error_response(
            "Empty team, more than six Pokemon, or an id that does not exist.",
            "Unknown Pokemon ids: [99999].",
        ),
        503: error_response(
            "The derived cache has not been built, so no matchup can be scored.",
            registry.CACHE_UNAVAILABLE_DETAIL,
        ),
    },
)
async def counter_team(payload: CounterTeamRequest) -> CounterTeamResponse:
    cache = require_cache()

    if not payload.pokemon_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one Pokemon id.",
        )
    if len(payload.pokemon_ids) > MAX_TEAM_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A team holds at most {MAX_TEAM_SIZE} Pokemon; "
            f"received {len(payload.pokemon_ids)}.",
        )

    try:
        return counter_service.build_counter_team(cache, payload.pokemon_ids)
    except counter_service.UnknownPokemon as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
