"""Counter-team recommendations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.routers.admin import require_cache
from api.schemas import CounterTeamRequest, CounterTeamResponse, ErrorResponse
from api.services import counterteam as counter_service

router = APIRouter(prefix="/counter-team", tags=["counter-team"])

MAX_ENEMIES = 6


@router.post(
    "",
    response_model=CounterTeamResponse,
    summary="Suggest a team that counters this one",
    description=(
        "Takes up to six Pokemon ids and returns six picks, each with a per-enemy "
        "breakdown, plus a coverage summary.\\n\\n"
        "**Type effectiveness only.** No damage formula, no stats, no moves, no "
        "speed. `offense` is the best multiplier a pick's own types land on the "
        "enemy, `defense` is the inverse of the worst multiplier it takes back, "
        "and the score is their product.\\n\\n"
        "Picks are chosen by marginal gain over six rounds: each round takes the "
        "candidate that most improves the current worst-covered enemies, so "
        "diminishing returns come from the structure rather than a decay factor.\\n\\n"
        "Stateless -- nothing is stored, and the whole computation runs off the "
        "in-memory derived cache."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Unknown or invalid team."},
        503: {"model": ErrorResponse, "description": "Derived cache is not built."},
    },
)
async def counter_team(payload: CounterTeamRequest) -> CounterTeamResponse:
    cache = require_cache()

    if not payload.pokemon_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one Pokemon id.",
        )
    if len(payload.pokemon_ids) > MAX_ENEMIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A team holds at most {MAX_ENEMIES} Pokemon; "
            f"received {len(payload.pokemon_ids)}.",
        )

    try:
        return counter_service.build_counter_team(cache, payload.pokemon_ids)
    except counter_service.UnknownPokemon as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
