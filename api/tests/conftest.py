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


def _payload(**overrides: Any) -> dict[str, Any]:
    """A Charizard-shaped payload carrying plenty of fields we never read."""
    base: dict[str, Any] = {
        "id": 6,
        "name": "charizard",
        "height": 17,
        "weight": 905,
        "is_default": True,
        "sprites": {"front_default": "https://img/6.png"},
        "types": [
            {"slot": 1, "type": {"name": "fire"}},
            {"slot": 2, "type": {"name": "flying"}},
        ],
        "stats": [
            {"stat": {"name": "hp"}, "base_stat": 78},
            {"stat": {"name": "attack"}, "base_stat": 84},
            {"stat": {"name": "defense"}, "base_stat": 78},
            {"stat": {"name": "special-attack"}, "base_stat": 109},
            {"stat": {"name": "special-defense"}, "base_stat": 85},
            {"stat": {"name": "speed"}, "base_stat": 100},
        ],
        "abilities": [
            {"ability": {"name": "blaze"}, "is_hidden": False},
            {"ability": {"name": "solar-power"}, "is_hidden": True},
        ],
        "moves": [
            {"move": {"name": "flamethrower", "url": "https://pokeapi.co/api/v2/move/53/"}},
            {"move": {"name": "fly", "url": "https://pokeapi.co/api/v2/move/19/"}},
            {"move": {"name": "scratch", "url": "https://pokeapi.co/api/v2/move/10/"}},
        ],
        # None of the below is consumed. All of it churns upstream.
        "base_experience": 267,
        "order": 7,
        "species": {"name": "charizard", "url": "https://pokeapi.co/api/v2/pokemon-species/6/"},
        "game_indices": [{"game_index": 180, "version": {"name": "red"}}],
        "held_items": [],
        "location_area_encounters": "https://pokeapi.co/api/v2/pokemon/6/encounters",
    }
    base.update(overrides)
    return base


@pytest.fixture
def payload() -> dict[str, Any]:
    return _payload()
