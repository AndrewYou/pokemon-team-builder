"""Section hashes over normalised payloads.

Section hashes rather than one row-level hash. A single hash can only say that
a Pokemon changed; four say *what* changed, which is the difference between
reporting "Attack 55 -> 60" and "Pikachu changed somehow".

Everything hashed here is a normalised structure, never a raw payload. Hashing
raw payloads reports a change on every run.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from api.sync.normalize import HASHED_SECTIONS, normalize_pokemon


def digest(value: Any) -> str:
    """Stable sha256 of any JSON-serialisable structure.

    `sort_keys` makes mapping order irrelevant; the compact separators keep the
    encoding canonical so equal data cannot produce different bytes.
    """
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def section_hash(normalized: dict[str, Any], section: str) -> str:
    """Hash one section of an already-normalised payload."""
    return digest(normalized.get(section))


def section_hashes(normalized: dict[str, Any]) -> dict[str, str]:
    """All section hashes, keyed as the database columns are named."""
    return {f"{section}_hash": section_hash(normalized, section) for section in HASHED_SECTIONS}


def hash_pokemon(payload: dict[str, Any]) -> dict[str, str]:
    """Normalise a raw payload and return its section hashes."""
    return section_hashes(normalize_pokemon(payload))
