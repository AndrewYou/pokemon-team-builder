"""The Pokemon catalog."""

from __future__ import annotations

import enum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from api.dependencies import SessionDep
from api.schemas import PokemonDetail, PokemonPage, TypeName, error_response
from api.services import catalog as catalog_service

router = APIRouter(prefix="/pokemon", tags=["catalog"])

# Reference data changes at most weekly, so a long browser cache is safe and
# keeps infinite scroll from re-fetching pages the user already has.
CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"


class SortOption(enum.StrEnum):
    """Catalog ordering. A dropdown rather than free text, and validated as an
    enum so nothing from the query string can reach SQL."""

    id = "id"
    name = "name"
    total = "total"
    hp = "hp"
    attack = "attack"
    speed = "speed"


class SortOrder(enum.StrEnum):
    """Sort direction, kept separate from the field.

    Folding direction into the field list would double the options and double
    again with every field added.
    """

    asc = "asc"
    desc = "desc"


@router.get(
    "",
    response_model=PokemonPage,
    summary="Browse the catalog",
    description=(
        "Cursor-paginated listing. Pass `next_cursor` back as `cursor` for the "
        "next page.\n\n"
        "Cursor rather than offset because the frontend scrolls infinitely: an "
        "OFFSET gets slower the deeper you scroll and can skip or repeat rows if "
        "the data shifts mid-scroll.\n\n"
        "`type` matches either type slot. `search` is a case-insensitive prefix "
        "match served by an index.\n\n"
        "`sort` accepts id, name, total, hp, attack, or speed, with `order` "
        "controlling direction. Id is always the final ordering term so that "
        "rows sharing a value -- hundreds of Pokemon share a base stat total -- "
        "cannot reorder between pages and produce duplicates or gaps."
    ),
    responses={
        400: error_response(
            "The cursor could not be decoded. Pass back a `next_cursor` verbatim.",
            "Malformed cursor",
        )
    },
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
    sort: Annotated[SortOption, Query(description="Field to order by.")] = SortOption.id,
    order: Annotated[SortOrder, Query(description="Direction.")] = SortOrder.asc,
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
            order=order.value,
        )
    except catalog_service.CursorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/{pokemon_id}",
    response_model=PokemonDetail,
    summary="Get one Pokemon",
    description="Catalog fields plus the full movepool. The raw payload column is never returned.",
    responses={404: error_response("No Pokemon with that id.", "Pokemon not found")},
)
async def get_pokemon(pokemon_id: int, response: Response, session: SessionDep) -> PokemonDetail:
    response.headers["Cache-Control"] = CACHE_CONTROL
    detail = await catalog_service.get_pokemon(session, pokemon_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pokemon not found")
    return detail
