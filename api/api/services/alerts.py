"""The user-facing alert feed.

Answers one question: what changed upstream that affects a team I built? Every
constraint in the query serves that -- scoped to this user's teams, limited to a
recent window, and excluding anything already dismissed.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Integer, Select, desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import ChangeAck, DataChange, Move, Pokemon, Team, TeamMember
from api.schemas import (
    AffectedTeam,
    AgedChangeResponse,
    AlertChange,
    AlertGroup,
    AlertsResponse,
    DismissAllResponse,
    DismissResponse,
)
from api.sync.alerts import alert_text

# How far back the feed looks. Older changes are still stored and still visible
# through /admin/changes; they simply stop being news.
WINDOW_DAYS = 7

ENTITY_POKEMON = "pokemon"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def move_id_from_path(field_path: str) -> int | None:
    """Extract the move id from a `moves[123]` path, if that is what this is."""
    if not field_path.startswith("moves[") or not field_path.endswith("]"):
        return None
    digits = field_path[6:-1]
    return int(digits) if digits.isdigit() else None


async def resolve_move_names(session: AsyncSession, field_paths: list[str]) -> dict[int, str]:
    """Look up every referenced move in one query rather than per row."""
    move_ids = {mid for path in field_paths if (mid := move_id_from_path(path)) is not None}
    if not move_ids:
        return {}
    rows = (await session.execute(select(Move.id, Move.name).where(Move.id.in_(move_ids)))).all()
    return {row.id: row.name for row in rows}


def group_alert_rows(rows: Sequence[Any], move_names: dict[int, str]) -> list[AlertGroup]:
    """Collapse the joined rows into one group per Pokemon.

    The join multiplies: a change to a Pokemon sitting on three of your teams
    comes back as three rows. Left ungrouped the feed would show the same alert
    three times, so both the teams and the changes are deduplicated -- one group
    naming all three teams, with each change listed once.

    Pure, so the collapsing can be tested without a database.
    """
    groups: dict[int, AlertGroup] = {}
    seen_changes: dict[int, set[int]] = {}

    for row in rows:
        group = groups.get(row.pokemon_id)
        if group is None:
            group = AlertGroup(
                pokemon_id=row.pokemon_id,
                pokemon_name=row.pokemon_name,
                sprite_url=row.sprite_url,
                affected_teams=[],
                changes=[],
            )
            groups[row.pokemon_id] = group
            seen_changes[row.pokemon_id] = set()

        if row.team_id not in {team.team_id for team in group.affected_teams}:
            group.affected_teams.append(AffectedTeam(team_id=row.team_id, team_name=row.team_name))

        if row.id not in seen_changes[row.pokemon_id]:
            seen_changes[row.pokemon_id].add(row.id)
            move_id = move_id_from_path(row.field_path)
            group.changes.append(
                AlertChange(
                    change_id=row.id,
                    field_path=row.field_path,
                    old_value=row.old_value,
                    new_value=row.new_value,
                    message=alert_text(
                        row.pokemon_name,
                        row.field_path,
                        row.old_value,
                        row.new_value,
                        move_name=move_names.get(move_id) if move_id else None,
                    ),
                    detected_at=row.detected_at,
                )
            )

    return list(groups.values())


def _visible_change_ids(user_id: uuid.UUID, cutoff: datetime.datetime) -> Select[tuple[int]]:
    """Ids of the changes this user can currently see.

    Shared by the feed and by dismiss-all so the two cannot disagree about what
    "every visible change" means.
    """
    acknowledged = (
        select(ChangeAck.data_change_id).where(ChangeAck.user_id == user_id).scalar_subquery()
    )
    return (
        select(DataChange.id)
        .join(Pokemon, Pokemon.id == DataChange.entity_id.cast(Integer))
        .join(TeamMember, TeamMember.pokemon_id == Pokemon.id)
        .join(Team, (Team.id == TeamMember.team_id) & (Team.user_id == user_id))
        .where(
            DataChange.entity_type == ENTITY_POKEMON,
            DataChange.detected_at >= cutoff,
            DataChange.id.notin_(acknowledged),
        )
    )


async def dismiss_all(session: AsyncSession, user_id: uuid.UUID) -> DismissAllResponse:
    """Acknowledge every change currently in this user's feed.

    One statement rather than a request per change: a sync can write dozens at
    once, and a browser firing dozens of POSTs to clear them is both slow and a
    good way to hit a connection limit.

    Idempotent, like the single dismissal -- ON CONFLICT DO NOTHING means
    re-running it acknowledges nothing further and still succeeds.
    """
    cutoff = _utcnow() - datetime.timedelta(days=WINDOW_DAYS)
    visible = list((await session.scalars(_visible_change_ids(user_id, cutoff))).all())
    if not visible:
        return DismissAllResponse(dismissed=0)

    result = await session.execute(
        insert(ChangeAck)
        .values([{"user_id": user_id, "data_change_id": change_id} for change_id in visible])
        .on_conflict_do_nothing(index_elements=["user_id", "data_change_id"])
        .returning(ChangeAck.data_change_id)
    )
    dismissed = len(result.all())
    await session.commit()
    return DismissAllResponse(dismissed=dismissed)


async def list_alerts(session: AsyncSession, user_id: uuid.UUID) -> AlertsResponse:
    """Undismissed recent changes to Pokemon on this user's teams.

    The dismissal filter is an anti-join rather than a NOT IN subquery, and it is
    scoped by user: one person dismissing an alert must not silence it for
    everybody else.
    """
    cutoff = _utcnow() - datetime.timedelta(days=WINDOW_DAYS)

    acknowledged = (
        select(ChangeAck.data_change_id).where(ChangeAck.user_id == user_id).scalar_subquery()
    )

    rows = (
        await session.execute(
            select(
                DataChange.id,
                DataChange.field_path,
                DataChange.old_value,
                DataChange.new_value,
                DataChange.detected_at,
                Pokemon.id.label("pokemon_id"),
                Pokemon.name.label("pokemon_name"),
                Pokemon.sprite_url,
                Team.id.label("team_id"),
                Team.name.label("team_name"),
            )
            # entity_id is text because not every entity is keyed by an integer;
            # the entity_type filter is what makes this cast safe.
            .join(Pokemon, Pokemon.id == DataChange.entity_id.cast(Integer))
            .join(TeamMember, TeamMember.pokemon_id == Pokemon.id)
            .join(Team, (Team.id == TeamMember.team_id) & (Team.user_id == user_id))
            .where(
                DataChange.entity_type == ENTITY_POKEMON,
                DataChange.detected_at >= cutoff,
                DataChange.id.notin_(acknowledged),
            )
            .order_by(desc(DataChange.detected_at), desc(DataChange.id))
        )
    ).all()

    move_names = await resolve_move_names(session, [row.field_path for row in rows])
    ordered = group_alert_rows(rows, move_names)

    return AlertsResponse(
        window_days=WINDOW_DAYS,
        total_changes=sum(len(group.changes) for group in ordered),
        affected_pokemon=len(ordered),
        groups=ordered,
    )


async def dismiss(
    session: AsyncSession, user_id: uuid.UUID, change_id: int
) -> DismissResponse | None:
    """Acknowledge one change for one user. Idempotent.

    Re-dismissing answers 200 with the original timestamp rather than raising on
    the composite primary key: a client retrying a request it already made has
    not done anything wrong, and the end state is what it asked for either way.
    """
    exists = await session.scalar(select(DataChange.id).where(DataChange.id == change_id))
    if exists is None:
        return None

    result = await session.execute(
        insert(ChangeAck)
        .values(user_id=user_id, data_change_id=change_id)
        .on_conflict_do_nothing(index_elements=["user_id", "data_change_id"])
        .returning(ChangeAck.acknowledged_at)
    )
    inserted = result.scalar_one_or_none()
    await session.commit()

    if inserted is not None:
        return DismissResponse(
            change_id=change_id, acknowledged_at=inserted, already_dismissed=False
        )

    # Nothing inserted means the row was already there; report when it happened.
    existing = await session.scalar(
        select(ChangeAck.acknowledged_at).where(
            ChangeAck.user_id == user_id, ChangeAck.data_change_id == change_id
        )
    )
    return DismissResponse(
        change_id=change_id,
        acknowledged_at=existing or _utcnow(),
        already_dismissed=True,
    )


async def age_change(session: AsyncSession, change_id: int, days: int) -> AgedChangeResponse | None:
    """Backdate a change so the alert window can be demonstrated immediately."""
    change = await session.get(DataChange, change_id)
    if change is None:
        return None

    before = change.detected_at
    after = before - datetime.timedelta(days=days)
    change.detected_at = after
    await session.commit()

    return AgedChangeResponse(
        change_id=change_id,
        days=days,
        detected_at_before=before,
        detected_at_after=after,
        still_in_window=after >= _utcnow() - datetime.timedelta(days=WINDOW_DAYS),
    )
