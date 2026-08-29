"""Shared fixtures. Nothing here touches the network or the database."""

from typing import Any

import pytest


def _stat(name: str, value: int) -> dict[str, Any]:
    return {"stat": {"name": name}, "base_stat": value}


@pytest.fixture
def bulbasaur() -> dict[str, Any]:
    """A PokeAPI-shaped Pokemon payload, trimmed to the parts we read."""
    return {
        "id": 1,
        "name": "bulbasaur",
        "height": 7,
        "weight": 69,
        "is_default": True,
        "sprites": {
            "front_default": "https://img/1.png",
            # Bulk that must not survive a trim.
            "other": {"official-artwork": {"front_default": "https://img/big.png"}},
            "versions": {"generation-i": {"red-blue": {"front_default": "x"}}},
        },
        "types": [
            {"slot": 2, "type": {"name": "poison"}},
            {"slot": 1, "type": {"name": "grass"}},
        ],
        "stats": [
            _stat("hp", 45),
            _stat("attack", 49),
            _stat("defense", 49),
            _stat("special-attack", 65),
            _stat("special-defense", 65),
            _stat("speed", 45),
        ],
        "abilities": [
            {"ability": {"name": "overgrow"}, "is_hidden": False},
            {"ability": {"name": "chlorophyll"}, "is_hidden": True},
        ],
        "moves": [
            {
                "move": {"name": "tackle", "url": "https://pokeapi.co/api/v2/move/33/"},
                "version_group_details": [{"level_learned_at": 1}] * 20,
            },
            {
                "move": {"name": "growl", "url": "https://pokeapi.co/api/v2/move/45/"},
                "version_group_details": [{"level_learned_at": 3}] * 20,
            },
        ],
        "game_indices": [{"game_index": 153}] * 20,
        "held_items": [{"item": {"name": "berry"}}],
        "cries": {"latest": "x.ogg"},
    }


@pytest.fixture
def tackle() -> dict[str, Any]:
    """A PokeAPI-shaped move payload."""
    return {
        "id": 33,
        "name": "tackle",
        "type": {"name": "normal"},
        "damage_class": {"name": "physical"},
        "power": 40,
        "accuracy": 100,
        "priority": 0,
        "effect_chance": None,
        "flavor_text_entries": [{"flavor_text": "x"}] * 50,
        "learned_by_pokemon": [{"name": "p"}] * 200,
        "machines": [],
    }
