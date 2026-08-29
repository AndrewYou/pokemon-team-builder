"""User-owned data: accounts, teams, and team slots."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


class AppUser(Base):
    """An account. Named app_user because `user` is reserved in Postgres."""

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    teams: Mapped[list[Team]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Team(Base):
    """A team of up to six Pokemon."""

    __tablename__ = "team"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[AppUser] = relationship(back_populates="teams")
    # passive_deletes hands deletion to the database's ON DELETE CASCADE instead
    # of letting SQLAlchemy load every child and null its foreign key first.
    members: Mapped[list[TeamMember]] = relationship(
        back_populates="team", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_team_user_id", "user_id"),)


class TeamMember(Base):
    """One Pokemon occupying one slot on a team.

    A surrogate primary key rather than (team_id, slot): slot is mutable under
    drag-and-drop reordering, and a primary key that changes on every reorder
    is a poor identity.
    """

    __tablename__ = "team_member"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"), nullable=False)
    pokemon_id: Mapped[int] = mapped_column(
        ForeignKey("pokemon.id", ondelete="RESTRICT"), nullable=False
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False)

    team: Mapped[Team] = relationship(back_populates="members")

    __table_args__ = (
        # Enforced by the database, not by application code.
        UniqueConstraint("team_id", "slot", name="uq_team_member_team_slot"),
        UniqueConstraint("team_id", "pokemon_id", name="uq_team_member_team_pokemon"),
        CheckConstraint("slot BETWEEN 1 AND 6", name="ck_team_member_slot_range"),
        # The change-alert join runs from a changed Pokemon back to the teams
        # containing it, so this index is read in the pokemon_id direction.
        Index("ix_team_member_pokemon_id", "pokemon_id"),
    )
