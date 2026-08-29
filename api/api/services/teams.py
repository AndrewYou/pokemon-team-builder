"""Team CRUD and roster replacement."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Pokemon, Team, TeamMember
from api.schemas import TeamMemberRead, TeamRead

MAX_ROSTER = 6


class RosterError(ValueError):
    """The submitted roster cannot be stored."""


async def _load_members(session: AsyncSession, team_id: int) -> list[TeamMemberRead]:
    """Roster for one team, ordered by slot."""
    rows = (
        await session.execute(
            select(
                TeamMember.slot,
                TeamMember.pokemon_id,
                Pokemon.name,
                Pokemon.sprite_url,
                Pokemon.type1,
                Pokemon.type2,
            )
            .join(Pokemon, Pokemon.id == TeamMember.pokemon_id)
            .where(TeamMember.team_id == team_id)
            .order_by(TeamMember.slot)
        )
    ).all()
    return [
        TeamMemberRead(
            slot=row.slot,
            pokemon_id=row.pokemon_id,
            name=row.name,
            sprite_url=row.sprite_url,
            types=[t for t in (row.type1, row.type2) if t],
        )
        for row in rows
    ]


async def to_read(session: AsyncSession, team: Team) -> TeamRead:
    return TeamRead(
        id=team.id,
        name=team.name,
        created_at=team.created_at,
        updated_at=team.updated_at,
        members=await _load_members(session, team.id),
    )


async def get_team(session: AsyncSession, user_id: uuid.UUID, team_id: int) -> Team | None:
    """Fetch a team owned by this user.

    Scoped by user_id in the query itself. Another user's team is simply not
    found, which the router turns into a 404: a 403 would confirm that the id
    exists and belongs to somebody.
    """
    team: Team | None = await session.scalar(
        select(Team).where(Team.id == team_id, Team.user_id == user_id)
    )
    return team


async def list_teams(session: AsyncSession, user_id: uuid.UUID) -> list[TeamRead]:
    teams = list(
        await session.scalars(
            select(Team).where(Team.user_id == user_id).order_by(Team.created_at.desc())
        )
    )
    return [await to_read(session, team) for team in teams]


async def create_team(session: AsyncSession, user_id: uuid.UUID, name: str) -> TeamRead:
    team = Team(user_id=user_id, name=name)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return await to_read(session, team)


async def rename_team(session: AsyncSession, team: Team, name: str) -> TeamRead:
    team.name = name
    await session.commit()
    await session.refresh(team)
    return await to_read(session, team)


async def delete_team(session: AsyncSession, team: Team) -> None:
    """Delete a team. Members go with it via ON DELETE CASCADE."""
    await session.delete(team)
    await session.commit()


async def replace_roster(session: AsyncSession, team: Team, pokemon_ids: list[int]) -> TeamRead:
    """Replace the entire roster in one transaction.

    Delete-then-insert rather than a diff. The submitted array is the desired
    end state, and computing a minimal set of moves would have to sequence
    updates around the UNIQUE(team_id, slot) constraint for no benefit.
    """
    if len(pokemon_ids) > MAX_ROSTER:
        raise RosterError(
            f"A team holds at most {MAX_ROSTER} Pokemon; received {len(pokemon_ids)}."
        )

    duplicates = sorted({i for i in pokemon_ids if pokemon_ids.count(i) > 1})
    if duplicates:
        raise RosterError(f"Duplicate Pokemon are not allowed: {duplicates}.")

    if pokemon_ids:
        known = set(
            (await session.scalars(select(Pokemon.id).where(Pokemon.id.in_(pokemon_ids)))).all()
        )
        unknown = [i for i in pokemon_ids if i not in known]
        if unknown:
            raise RosterError(f"Unknown Pokemon ids: {unknown}.")

    await session.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    if pokemon_ids:
        session.add_all(
            [
                TeamMember(team_id=team.id, pokemon_id=pokemon_id, slot=slot)
                for slot, pokemon_id in enumerate(pokemon_ids, start=1)
            ]
        )
    # Touch the parent so updated_at reflects a roster change, not just a rename.
    team.updated_at = func.now()
    await session.commit()
    await session.refresh(team)
    return await to_read(session, team)
