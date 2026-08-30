"""The derived layer: type chart and defensive vectors, held in memory.

Built once from Postgres and never materialised back into tables. Level-50
conversion and effectiveness maths belong here, not at write time, so that the
sync job keeps comparing base values against base values.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.battle.damage import hp_at_level_50, stat_at_level_50
from api.derived.moves import BestMove, MoveRow, collapse
from api.derived.typechart import (
    LEGAL_DEFENSIVE_VALUES,
    TYPE_INDEX,
    TypeChart,
    build_chart,
    defensive_vector,
)
from api.ingest.normalize import CANONICAL_TYPES
from api.models import Move, Pokemon, PokemonMove
from api.models import TypeChart as TypeChartRow


@dataclass(frozen=True, slots=True)
class PokemonMeta:
    """The catalog fields needed to describe a Pokemon without touching the DB.

    Counter-team selection is required to run entirely off in-memory derived
    data, so the display fields have to live here rather than being joined back
    in per request.
    """

    id: int
    name: str
    sprite_url: str | None
    types: tuple[str, ...]


@dataclass(slots=True)
class DerivedCache:
    """Immutable snapshot of everything derived from reference data."""

    chart: TypeChart
    # pokemon_id -> row index into `vectors`.
    pokemon_index: dict[int, int]
    # Row index -> pokemon_id, so a row can be traced back.
    pokemon_ids: list[int]
    # Row index -> display metadata, aligned with `vectors`.
    meta: list[PokemonMeta]
    # Shape (n_pokemon, 18). Column order is CANONICAL_TYPES.
    vectors: npt.NDArray[np.float64]
    # Level-50 stats, column order hp, atk, def, spatk, spdef, speed.
    stats: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 6)))
    # Base stat totals, for the tiebreak after marginal gain.
    totals: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))
    # Collapsed movepools, aligned with `vectors`.
    moves: list[list[BestMove]] = field(default_factory=list)
    # The same movepools as padded arrays, so scoring is broadcast rather than
    # looped. Padding columns carry power 0, which cannot win a max.
    move_type_index: npt.NDArray[np.int64] = field(
        default_factory=lambda: np.zeros((0, 0), dtype=np.int64)
    )
    move_power: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    move_physical: npt.NDArray[np.bool_] = field(
        default_factory=lambda: np.zeros((0, 0), dtype=bool)
    )
    move_accuracy: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    move_stab: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    built_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    build_ms: float = 0.0
    # How many rows came from the database, as opposed to the 1.0 defaults
    # build_chart fills in. An empty table still yields a complete-looking
    # nested dict of neutral multipliers, so the count is the only honest signal.
    chart_rows_loaded: int = 0
    type_index: dict[str, int] = field(default_factory=lambda: dict(TYPE_INDEX))

    @property
    def pokemon_count(self) -> int:
        return len(self.pokemon_ids)

    def meta_for(self, pokemon_id: int) -> PokemonMeta:
        row = self.pokemon_index.get(pokemon_id)
        if row is None:
            raise KeyError(pokemon_id)
        return self.meta[row]

    @property
    def chart_complete(self) -> bool:
        """True when every pairing was actually read, not defaulted.

        Serving matchups off a defaulted chart would answer 1.0 for everything:
        wrong, and indistinguishable from a genuinely neutral matchup.
        """
        return self.chart_rows_loaded == len(CANONICAL_TYPES) ** 2

    def vector_for(self, pokemon_id: int) -> npt.NDArray[np.float64]:
        """The 18 defensive multipliers for one Pokemon."""
        row = self.pokemon_index.get(pokemon_id)
        if row is None:
            raise KeyError(pokemon_id)
        vector: npt.NDArray[np.float64] = self.vectors[row]
        return vector

    def multiplier(self, pokemon_id: int, attacking: str) -> float:
        """How much damage one Pokemon takes from one attacking type."""
        column = self.type_index.get(attacking)
        if column is None:
            raise KeyError(attacking)
        return float(self.vector_for(pokemon_id)[column])

    def vector_as_dict(self, pokemon_id: int) -> dict[str, float]:
        vector = self.vector_for(pokemon_id)
        return {name: float(vector[index]) for name, index in self.type_index.items()}

    def illegal_value_count(self) -> int:
        """Entries outside the six values dual typing can produce.

        A non-zero count means the chart is wrong, and every downstream damage
        calculation is quietly wrong with it.
        """
        if self.vectors.size == 0:
            return 0
        legal = np.isin(self.vectors, np.array(sorted(LEGAL_DEFENSIVE_VALUES)))
        return int((~legal).sum())


MoveArrays = tuple[
    npt.NDArray[np.int64],
    npt.NDArray[np.float64],
    npt.NDArray[np.bool_],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]


def pack_moves(moves: list[list[BestMove]], meta: list[PokemonMeta]) -> MoveArrays:
    """Movepools as padded arrays, so scoring broadcasts instead of looping.

    Padding columns carry power 0. That matters: the damage formula adds a
    constant 2, so a zero-power column still produces damage unless it is
    masked, and `power > 0` is the mask everything downstream uses.
    """
    count = len(moves)
    width = max((len(entry) for entry in moves), default=1) or 1

    type_index = np.zeros((count, width), dtype=np.int64)
    power = np.zeros((count, width), dtype=np.float64)
    physical = np.zeros((count, width), dtype=bool)
    accuracy = np.ones((count, width), dtype=np.float64)
    stab = np.ones((count, width), dtype=np.float64)

    for index, entries in enumerate(moves):
        own_types = set(meta[index].types)
        for column, move in enumerate(entries):
            type_index[index, column] = TYPE_INDEX[move.type]
            power[index, column] = move.power
            physical[index, column] = move.damage_class == "physical"
            accuracy[index, column] = (move.accuracy or 100) / 100
            # STAB depends only on attacker and move, so it is settled here
            # rather than recomputed against every defender.
            stab[index, column] = 1.5 if move.type in own_types else 1.0

    return type_index, power, physical, accuracy, stab


async def build_cache(session: AsyncSession) -> DerivedCache:
    """Read reference data and compute the derived structures."""
    started = time.perf_counter()

    chart_rows = await session.execute(
        select(
            TypeChartRow.attacking_type,
            TypeChartRow.defending_type,
            TypeChartRow.multiplier,
        )
    )
    chart_tuples = [(row.attacking_type, row.defending_type, row.multiplier) for row in chart_rows]
    chart = build_chart(chart_tuples)

    pokemon_rows = (
        await session.execute(
            select(
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
            ).order_by(Pokemon.id)
        )
    ).all()

    pokemon_ids = [row.id for row in pokemon_rows]
    pokemon_index = {pokemon_id: index for index, pokemon_id in enumerate(pokemon_ids)}
    meta = [
        PokemonMeta(
            id=row.id,
            name=row.name,
            sprite_url=row.sprite_url,
            types=tuple(t for t in (row.type1, row.type2) if t),
        )
        for row in pokemon_rows
    ]

    # Allocated up front rather than appended: the shape is known, and this
    # keeps the array contiguous for the counter-team scoring that comes later.
    vectors = np.ones((len(pokemon_rows), len(CANONICAL_TYPES)), dtype=np.float64)
    for index, row in enumerate(pokemon_rows):
        vectors[index] = defensive_vector(chart, row.type1, row.type2)

    # One query for every movepool rather than one per Pokemon: 79k join rows
    # is a single round trip, and 1025 of them is not.
    move_rows = (
        await session.execute(
            select(
                PokemonMove.pokemon_id,
                Move.id,
                Move.name,
                Move.type,
                Move.damage_class,
                Move.power,
                Move.accuracy,
            ).join(Move, Move.id == PokemonMove.move_id)
        )
    ).all()

    by_pokemon: dict[int, list[MoveRow]] = {}
    for row in move_rows:
        by_pokemon.setdefault(row.pokemon_id, []).append(
            MoveRow(
                id=row.id,
                name=row.name,
                type=row.type,
                damage_class=row.damage_class,
                power=row.power,
                accuracy=row.accuracy,
            )
        )

    moves = [collapse(by_pokemon.get(pokemon_id, [])) for pokemon_id in pokemon_ids]

    stats = np.array(
        [
            [
                hp_at_level_50(row.base_hp),
                stat_at_level_50(row.base_atk),
                stat_at_level_50(row.base_def),
                stat_at_level_50(row.base_spatk),
                stat_at_level_50(row.base_spdef),
                stat_at_level_50(row.base_speed),
            ]
            for row in pokemon_rows
        ],
        dtype=np.float64,
    ).reshape(len(pokemon_rows), 6)

    totals = np.array(
        [
            row.base_hp
            + row.base_atk
            + row.base_def
            + row.base_spatk
            + row.base_spdef
            + row.base_speed
            for row in pokemon_rows
        ],
        dtype=np.float64,
    )

    (
        move_type_index,
        move_power,
        move_physical,
        move_accuracy,
        move_stab,
    ) = pack_moves(moves, meta)

    return DerivedCache(
        chart=chart,
        pokemon_index=pokemon_index,
        pokemon_ids=pokemon_ids,
        meta=meta,
        vectors=vectors,
        stats=stats,
        totals=totals,
        moves=moves,
        move_type_index=move_type_index,
        move_power=move_power,
        move_physical=move_physical,
        move_accuracy=move_accuracy,
        move_stab=move_stab,
        built_at=datetime.datetime.now(datetime.UTC),
        build_ms=(time.perf_counter() - started) * 1000,
        chart_rows_loaded=len(chart_tuples),
    )
