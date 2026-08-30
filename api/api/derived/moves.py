"""Collapsing a movepool down to the moves that can actually win.

A Pokemon knows up to ~40 damaging moves, but within one (type, damage class)
group the attacker's stat, the defender's stat and the effectiveness multiplier
are all identical, so damage is a strictly increasing function of power alone.
The highest-power move in a group therefore beats every other move in it
against *every* defender. Keeping only that one is lossless, not a heuristic,
and takes a movepool to 10-15 entries.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.ingest.normalize import CANONICAL_TYPES

CANONICAL_TYPE_SET = frozenset(CANONICAL_TYPES)
STATUS = "status"


@dataclass(frozen=True, slots=True)
class BestMove:
    """The strongest move a Pokemon has of one type and damage class."""

    id: int
    name: str
    type: str
    damage_class: str
    power: int
    accuracy: int | None


@dataclass(frozen=True, slots=True)
class MoveRow:
    """A raw movepool entry, as read from the database."""

    id: int
    name: str
    type: str
    damage_class: str
    power: int | None
    accuracy: int | None


def collapse(moves: list[MoveRow]) -> list[BestMove]:
    """Keep the highest-power move per (type, damage class).

    Status moves are dropped: they have no power and deal no damage, so they
    cannot participate in a damage model.

    Moves whose type is not one of the 18 are dropped too. PokeAPI carries
    shadow-type moves, and Tera Blast becomes Stellar; either would raise a
    KeyError on the defensive-vector lookup, which is a crash rather than a
    wrong answer but still a crash in the middle of a request.
    """
    best: dict[tuple[str, str], MoveRow] = {}

    for move in moves:
        if move.damage_class == STATUS or not move.power:
            continue
        if move.type not in CANONICAL_TYPE_SET:
            continue

        key = (move.type, move.damage_class)
        incumbent = best.get(key)
        # Ties resolve on id so the choice is deterministic rather than
        # dependent on the order rows came back in.
        if (
            incumbent is None
            or move.power > incumbent.power  # type: ignore[operator]
            or (move.power == incumbent.power and move.id < incumbent.id)
        ):
            best[key] = move

    return sorted(
        (
            BestMove(
                id=move.id,
                name=move.name,
                type=move.type,
                damage_class=move.damage_class,
                power=move.power,  # type: ignore[arg-type]
                accuracy=move.accuracy,
            )
            for move in best.values()
        ),
        key=lambda move: (move.type, move.damage_class),
    )
