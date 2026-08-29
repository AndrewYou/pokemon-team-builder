"""Background job bookkeeping.

Seeds and syncs take minutes. Running one inside a request would hang the
Swagger page and risk a proxy timeout mid-demo, so the HTTP layer records a row
here, hands the work to a background task, and answers 202 immediately. This
table is what makes the job pollable afterwards.

Deliberately separate from sync_run: that table describes a change-detection
pass and carries counters and a source enum specific to it. Overloading it with
seeds would pollute the change-detection history.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, desc, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Base


class JobStatus(enum.StrEnum):
    """Lifecycle of a background job."""

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobKind(enum.StrEnum):
    """Known job kinds. Stored as text so later phases can add kinds without a
    migration; this enum exists for callers, not for the column type."""

    seed = "seed"
    sync = "sync"


# The states in which a job still owns its kind. Used by the partial unique
# index below and by the 409 check in the router.
ACTIVE_STATUSES = (JobStatus.pending, JobStatus.running)


class Job(Base):
    """One background job execution."""

    __tablename__ = "job"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        ENUM(
            JobStatus,
            name="job_status",
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
        server_default=text("'pending'"),
    )
    # Human-readable current phase, e.g. "fetching pokemon".
    detail: Mapped[str | None] = mapped_column(String(200))
    # Row counts on success.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Full failure text on error. A job that failed silently is worse than one
    # that failed loudly, and this is where the reviewer looks.
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Newest-first listing for /admin/jobs.
        Index("ix_job_kind_created_at", "kind", desc("created_at")),
        # Concurrency guard enforced by the database, not just by the router's
        # check: two simultaneous requests could both pass an application-level
        # test and start duplicate crawls.
        Index(
            "uq_job_active_kind",
            "kind",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )
