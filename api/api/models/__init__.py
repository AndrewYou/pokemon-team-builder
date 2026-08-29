"""SQLAlchemy models.

Every model module MUST be imported here. Alembic autogenerate only sees classes
that have actually been imported by the time env.py builds its metadata -- a
models package whose __init__ imports nothing produces a confidently empty
migration that applies cleanly and creates no tables.
"""

from api.db import Base
from api.models.job import ACTIVE_STATUSES, Job, JobKind, JobStatus
from api.models.reference import (
    Move,
    Pokemon,
    PokemonAbility,
    PokemonMove,
    TypeChart,
)
from api.models.sync import ChangeAck, DataChange, SyncRun, SyncSource
from api.models.user import AppUser, Team, TeamMember

__all__ = [
    "ACTIVE_STATUSES",
    "AppUser",
    "Base",
    "ChangeAck",
    "DataChange",
    "Job",
    "JobKind",
    "JobStatus",
    "Move",
    "Pokemon",
    "PokemonAbility",
    "PokemonMove",
    "SyncRun",
    "SyncSource",
    "Team",
    "TeamMember",
    "TypeChart",
]
