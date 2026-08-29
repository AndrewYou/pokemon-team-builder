"""Change detection: sync runs, the diffs they produce, and user acknowledgements."""

from __future__ import annotations

import datetime
import enum
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Base


class SyncSource(enum.StrEnum):
    """Where a sync run got its data.

    `stale` records a run that fell back to the existing snapshot because the
    upstream fetch failed -- distinct from `fixture`, which is a deliberate
    offline seed. Keeping them apart is what stops a failed sync from being
    silently indistinguishable from a successful one.
    """

    live = "live"
    fixture = "fixture"
    stale = "stale"


class SyncRun(Base):
    """One execution of the PokeAPI sync job."""

    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Null while the run is still in flight.
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # server_default, not a Python-side default: these are NOT NULL counters, and
    # a Python default is invisible to any insert that does not go through the ORM.
    records_scanned: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    changes_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    source: Mapped[SyncSource] = mapped_column(
        # Declared explicitly as a Postgres native enum. values_callable pins the
        # stored labels to the enum *values*; without it SQLAlchemy persists the
        # member *names*, which is a silent mismatch when the two ever diverge.
        ENUM(
            SyncSource,
            name="sync_source",
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (Index("ix_sync_run_started_at", "started_at"),)


class DataChange(Base):
    """A single field-level difference detected during a sync run."""

    __tablename__ = "data_change"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(
        ForeignKey("sync_run.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Text, not int: entity ids are integers today but type_chart is keyed by a
    # pair of strings, so this column has to hold more than one shape.
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    # Null on either side is meaningful: a field appearing or disappearing.
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # The changes feed is read newest-first, so the index is descending to
        # match the ORDER BY and let Postgres skip a sort node.
        Index("ix_data_change_detected_at", desc("detected_at")),
        Index("ix_data_change_sync_run_id", "sync_run_id"),
        Index("ix_data_change_entity", "entity_type", "entity_id"),
    )


class ChangeAck(Base):
    """A user dismissing one detected change. Composite key: a user can
    acknowledge a given change exactly once."""

    __tablename__ = "change_ack"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    data_change_id: Mapped[int] = mapped_column(
        ForeignKey("data_change.id", ondelete="CASCADE"), primary_key=True
    )
    acknowledged_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_change_ack_data_change_id", "data_change_id"),)
