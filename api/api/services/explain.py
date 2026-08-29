"""EXPLAIN ANALYZE for the queries the application actually runs.

Index usage is easy to assert in a comment and easy to lose in a refactor. This
exposes the real plan for the real queries so it can be checked from a browser
rather than taken on trust.
"""

from __future__ import annotations

import enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ExplainQuery(enum.StrEnum):
    """The queries whose plans are worth watching."""

    name_search = "name_search"
    type_filter = "type_filter"
    catalog_page = "catalog_page"
    team_members_by_pokemon = "team_members_by_pokemon"


# Parameters are inlined rather than bound, because a bound parameter makes the
# planner choose a generic plan and the point here is to see the specific one.
_QUERIES: dict[ExplainQuery, str] = {
    ExplainQuery.name_search: (
        "SELECT id, name FROM pokemon WHERE name LIKE 'char%' ORDER BY id LIMIT 49"
    ),
    ExplainQuery.type_filter: (
        "SELECT id, name FROM pokemon WHERE type1 = 'fire' OR type2 = 'fire' ORDER BY id LIMIT 49"
    ),
    ExplainQuery.catalog_page: ("SELECT id, name FROM pokemon WHERE id > 100 ORDER BY id LIMIT 49"),
    ExplainQuery.team_members_by_pokemon: (
        "SELECT team_id, slot FROM team_member WHERE pokemon_id = 6"
    ),
}


async def explain(session: AsyncSession, query: ExplainQuery) -> tuple[str, list[str]]:
    """Return the SQL and its EXPLAIN ANALYZE plan."""
    sql = _QUERIES[query]
    rows = (await session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {sql}"))).all()
    return sql, [row[0] for row in rows]
