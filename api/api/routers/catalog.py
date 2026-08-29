"""The Pokemon catalog."""

from __future__ import annotations

import enum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from api.dependencies import SessionDep
from api.schemas import ErrorResponse, PokemonDetail, PokemonPage, TypeName
from api.services import catalog as catalog_service

router = APIRouter(prefix="/pokemon", tags=["catalog"])

# Reference data changes at most weekly, so a long browser cache is safe and
# keeps infinite scroll from re-fetching pages the user already has.
CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"


class SortOption(enum.StrEnum):
    """Catalog ordering. A dropdown rather than free text."""

    id = "id"
    name = "name"


@router.get(
    "",
    response_model=PokemonPage,
    summary="Browse the catalog",
    description=(
        "Cursor-paginated listing. Pass `next_cursor` back as `cursor` for the "
        "next page.\\n\\n"
        "Cursor rather than offset because the frontend scrolls infinitely: an "
        "OFFSET gets slower the deeper you scroll and can skip or repeat rows if "
        "the data shifts mid-scroll.\\n\\n"
        "`type` matches either type slot. `search` is a case-insensitive prefix "
        "match served by an index."
    ),
    responses={400: {"model": ErrorResponse, "description": "Malformed cursor."}},
)
async def list_pokemon(
    response: Response,
    session: SessionDep,
    cursor: Annotated[str | None, Query(description="Opaque cursor from a previous page.")] = None,
    limit: Annotated[
        int, Query(ge=1, le=catalog_service.MAX_LIMIT)
    ] = catalog_service.DEFAULT_LIMIT,
    type: Annotated[  # noqa: A002 - the query parameter is named `type` in the API
        TypeName | None, Query(description="Match either type slot.")
    ] = None,
    search: Annotated[
        str | None, Query(description="Case-insensitive name prefix, e.g. `pika`.")
    ] = None,
    sort: Annotated[SortOption, Query(description="Ordering.")] = SortOption.id,
) -> PokemonPage:
    response.headers["Cache-Control"] = CACHE_CONTROL
    try:
        return await catalog_service.list_pokemon(
            session,
            cursor=cursor,
            limit=limit,
            type_name=type.value if type else None,
            search=search,
            sort=sort.value,
        )
    except catalog_service.CursorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/{pokemon_id}",
    response_model=PokemonDetail,
    summary="Get one Pokemon",
    description="Catalog fields plus the full movepool. The raw payload column is never returned.",
    responses={404: {"model": ErrorResponse, "description": "No Pokemon with that id."}},
)
async def get_pokemon(pokemon_id: int, response: Response, session: SessionDep) -> PokemonDetail:
    response.headers["Cache-Control"] = CACHE_CONTROL
    detail = await catalog_service.get_pokemon(session, pokemon_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pokemon not found")
    return detail
