"""Human-readable rendering of a detected change.

One function, used by two callers that must agree exactly: the simulator
predicts the alert a change will produce, and the changes feed renders the
change once it has been detected. If these diverged, a demo comparing the
predicted string against the UI would show a mismatch that means nothing.
"""

from __future__ import annotations

import re

# stats.<api stat name> -> the label a player recognises.
STAT_LABELS: dict[str, str] = {
    "hp": "HP",
    "attack": "Attack",
    "defense": "Defense",
    "special-attack": "Special Attack",
    "special-defense": "Special Defense",
    "speed": "Speed",
}

_MOVE_PATH = re.compile(r"^moves\[(\d+)\]$")
_TYPE_PATH = re.compile(r"^types\[(\d+)\]$")

TYPE_SLOT_LABELS = {0: "primary type", 1: "secondary type"}


def display_name(name: str) -> str:
    """`pikachu` -> `Pikachu`, `mr-mime` -> `Mr-Mime`."""
    return "-".join(part.capitalize() for part in name.split("-"))


def alert_text(
    pokemon_name: str,
    field_path: str,
    old_value: str | int | None,
    new_value: str | int | None,
    move_name: str | None = None,
) -> str:
    """Render one change as a sentence.

    `old_value` is what our snapshot held and `new_value` is what upstream now
    reports, matching the direction the sync writes them.
    """
    subject = display_name(pokemon_name)

    if field_path.startswith("stats."):
        stat = field_path.removeprefix("stats.")
        label = STAT_LABELS.get(stat, stat.replace("-", " ").title())
        return f"{subject}'s {label} changed from {old_value} to {new_value}"

    type_match = _TYPE_PATH.match(field_path)
    if type_match:
        slot = int(type_match.group(1))
        label = TYPE_SLOT_LABELS.get(slot, f"type {slot + 1}")
        if old_value is None:
            return f"{subject} gained a {label} of {new_value}"
        if new_value is None:
            return f"{subject} lost its {label} of {old_value}"
        return f"{subject}'s {label} changed from {old_value} to {new_value}"

    if field_path == "sprite":
        return f"{subject}'s sprite changed"

    move_match = _MOVE_PATH.match(field_path)
    if move_match:
        # Capitalise a real move name; leave the id fallback as a placeholder,
        # since "Move #85" reads as though that were its title.
        move = display_name(move_name) if move_name else f"move #{move_match.group(1)}"
        if old_value is None:
            return f"{subject} learned {move}"
        return f"{subject} forgot {move}"

    if field_path.startswith("abilities."):
        ability = display_name(field_path.removeprefix("abilities."))
        if old_value is None:
            return f"{subject} gained the ability {ability}"
        if new_value is None:
            return f"{subject} lost the ability {ability}"
        return f"{subject}'s ability {ability} changed from {old_value} to {new_value}"

    return f"{subject}'s {field_path} changed from {old_value} to {new_value}"
