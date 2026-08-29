"""Catalog queries: paginated listing, filtering, and detail.

Explicit columns everywhere. The `raw` JSONB column is never selected: it is
several kilobytes per row and exists for backfill, not for serving.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from sqlalchemy import Select, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Move, Pokemon, PokemonMove
from api.schemas import (
    MoveSummary,
    PokemonDetail,
    PokemonPage,
    PokemonStats,
    PokemonSummary,
)

DEFAULT_LIMIT = 48
MAX_LIMIT = 100

# An allowlist, not a lookup into user input. The request carries a key from
# this mapping and never a column name, so nothing from the query string
# reaches SQL.
SORTABLE: dict[str, Any] = {
    "id": Pokemon.id,
    "name": Pokemon.name,
    "total": (
        Pokemon.base_hp
        + Pokemon.base_atk
        + Pokemon.base_def
        + Pokemon.base_spatk
        + Pokemon.base_spdef
        + Pokemon.base_speed
    ),
    "hp": Pokemon.base_hp,
    "attack": Pokemon.base_atk,
    "speed": Pokemon.base_speed,
}

_LIST_COLUMNS = (
    Pokemon.id,
    Pokemon.name,
    Pokemon.sprite_url,
    Pokemon.type1,
    Pokemon.type2,
    Pokemon.base_hp,
    Pokemon.base_atk,
    Pokemon.base_def,
    Pokemon.base_spatk,
    Pokemon.base_spdef,
    Pokemon.base_speed,
)


class CursorError(ValueError):
    """The supplied cursor could not be decoded."""


def encode_cursor(sort_key: str | int, pokemon_id: int) -> str:
    """Opaque cursor over (sort key, id).

    The id is part of the key so the ordering is total: sorting by name alone
    would be ambiguous between rows sharing a name, and a page boundary landing
    inside such a group would skip or repeat entries.
    """
    payload = json.dumps({"k": sort_key, "i": pokemon_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str | int, int]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload["k"], int(payload["i"])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CursorError("Malformed cursor") from exc


def _summary(row: Any) -> PokemonSummary:
    return PokemonSummary(
        id=row.id,
        name=row.name,
        sprite_url=row.sprite_url,
        types=[t for t in (row.type1, row.type2) if t],
        stats=PokemonStats(
            hp=row.base_hp,
            attack=row.base_atk,
            defense=row.base_def,
            special_attack=row.base_spatk,
            special_defense=row.base_spdef,
            speed=row.base_speed,
        ),
    )


def _apply_filters(
    statement: Select[Any], type_name: str | None, search: str | None
) -> Select[Any]:
    if type_name is not None:
        # Either slot: a Fire/Flying Pokemon must appear under both filters.
        statement = statement.where(or_(Pokemon.type1 == type_name, Pokemon.type2 == type_name))
    if search:
        # Stored names are lowercase, so lowering the term makes this
        # case-insensitive while staying a plain LIKE prefix -- which is what
        # the text_pattern_ops index can serve. ILIKE would force a seq scan.
        statement = statement.where(Pokemon.name.like(f"{search.strip().lower()}%"))
    return statement


async def list_pokemon(
    session: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    type_name: str | None = None,
    search: str | None = None,
    sort: str = "id",
    order: str = "asc",
) -> PokemonPage:
    """One page of the catalog, keyset paginated.

    The sort key is selected alongside the row so the cursor can carry it,
    which is what lets a computed key like total base stats paginate at all.

    Id is always the final ordering term, in the same direction as the key.
    Without a tiebreaker, rows sharing a value -- and hundreds of Pokemon share
    a base stat total -- land in an arbitrary order that can differ between
    pages, producing duplicates and gaps. The direction has to match, because
    the keyset comparison is a row-value comparison over the same tuple.
    """
    sort_expression = SORTABLE.get(sort, SORTABLE["id"])
    descending = order == "desc"

    statement = select(*_LIST_COLUMNS, sort_expression.label("sort_key"))
    statement = _apply_filters(statement, type_name, search)

    if cursor:
        last_key, last_id = decode_cursor(cursor)
        # tuple_() rather than a bare Python tuple: this has to compile to a
        # SQL row-value comparison, which is what advances the key and the
        # tiebreaker together as one unit.
        pair = tuple_(sort_expression, Pokemon.id)
        anchor = tuple_(literal(last_key), literal(last_id))
        statement = statement.where(pair < anchor if descending else pair > anchor)

    ordering = (
        (sort_expression.desc(), Pokemon.id.desc())
        if descending
        else (sort_expression.asc(), Pokemon.id.asc())
    )

    # One extra row answers "is there a next page" without a second COUNT over
    # the whole filtered set.
    rows = (await session.execute(statement.order_by(*ordering).limit(limit + 1))).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(last.sort_key, last.id)

    return PokemonPage(
        items=[_summary(row) for row in page], next_cursor=next_cursor, has_more=has_more
    )


async def get_pokemon(session: AsyncSession, pokemon_id: int) -> PokemonDetail | None:
    """One Pokemon with its movepool."""
    row = (await session.execute(select(*_LIST_COLUMNS).where(Pokemon.id == pokemon_id))).first()
    if row is None:
        return None

    move_rows = (
        await session.execute(
            select(Move.id, Move.name, Move.type, Move.damage_class, Move.power, Move.accuracy)
            .join(PokemonMove, PokemonMove.move_id == Move.id)
            .where(PokemonMove.pokemon_id == pokemon_id)
            .order_by(Move.name)
        )
    ).all()

    summary = _summary(row)
    return PokemonDetail(
        **summary.model_dump(),
        moves=[
            MoveSummary(
                id=m.id,
                name=m.name,
                type=m.type,
                damage_class=m.damage_class,
                power=m.power,
                accuracy=m.accuracy,
            )
            for m in move_rows
        ],
    )
