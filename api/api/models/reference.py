"""Reference data synced from PokeAPI.

Everything in this module is mutable upstream: PokeAPI can and does revise
stats, types, and sprites. These tables are the prior copy that change
detection diffs against, which is the whole reason we snapshot rather than
proxy. The per-aspect *_hash columns exist so a sync can decide what changed
without deep-comparing every field.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Base


class Pokemon(Base):
    """A single Pokemon as returned by PokeAPI.

    Stats are BASE stats, stored exactly as fetched. Level-50 conversion belongs
    to the derived layer: converting at write time would make the sync job
    compare converted values against freshly fetched raw ones, and every row
    would look changed on every run.
    """

    __tablename__ = "pokemon"

    # Supplied by PokeAPI, not generated here, so autoincrement is off.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Nullable: PokeAPI genuinely returns a null front_default for some forms.
    sprite_url: Mapped[str | None] = mapped_column(String(500))

    type1: Mapped[str] = mapped_column(String(20), nullable=False)
    type2: Mapped[str | None] = mapped_column(String(20))

    base_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    base_atk: Mapped[int] = mapped_column(Integer, nullable=False)
    base_def: Mapped[int] = mapped_column(Integer, nullable=False)
    base_spatk: Mapped[int] = mapped_column(Integer, nullable=False)
    base_spdef: Mapped[int] = mapped_column(Integer, nullable=False)
    base_speed: Mapped[int] = mapped_column(Integer, nullable=False)

    height: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # Full upstream payload, kept so a new field can be backfilled without refetching.
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Per-aspect digests, so a diff can report *what* changed, not just *that*
    # something did. Sized for a hex sha256.
    stats_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    types_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    moves_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sprite_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    last_synced_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # The catalog filters on either slot, so both are indexed separately.
        Index("ix_pokemon_type1", "type1"),
        Index("ix_pokemon_type2", "type2"),
        # text_pattern_ops is required for LIKE 'pika%' to use an index at all:
        # the default collation-aware opclass cannot serve prefix matches.
        Index(
            "ix_pokemon_name_prefix",
            "name",
            postgresql_ops={"name": "text_pattern_ops"},
        ),
    )


class Move(Base):
    """A move, stored with the same raw-plus-hash shape as Pokemon."""

    __tablename__ = "move"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    damage_class: Mapped[str] = mapped_column(String(20), nullable=False)
    # Status moves have no power, and several moves never miss.
    power: Mapped[int | None] = mapped_column(Integer)
    accuracy: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_chance: Mapped[int | None] = mapped_column(Integer)

    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_move_type", "type"),)


class PokemonMove(Base):
    """Join table: which moves a Pokemon can learn."""

    __tablename__ = "pokemon_move"

    pokemon_id: Mapped[int] = mapped_column(
        ForeignKey("pokemon.id", ondelete="CASCADE"), primary_key=True
    )
    move_id: Mapped[int] = mapped_column(
        ForeignKey("move.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (Index("ix_pokemon_move_move_id", "move_id"),)


class PokemonAbility(Base):
    """An ability slot on a Pokemon. Keyed by name; abilities are not synced as
    their own entity yet, so there is nothing to point a foreign key at."""

    __tablename__ = "pokemon_ability"

    pokemon_id: Mapped[int] = mapped_column(
        ForeignKey("pokemon.id", ondelete="CASCADE"), primary_key=True
    )
    ability_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class TypeChart(Base):
    """Full 18x18 attacking/defending effectiveness matrix: 324 rows.

    Stored rather than hardcoded so it is diffable like any other reference
    data. Numeric, not float, because the multipliers are exact values
    (0, 0.5, 1, 2) that get multiplied together and compared.
    """

    __tablename__ = "type_chart"

    attacking_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    defending_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
