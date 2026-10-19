"""The scheduler: which schedule rows are due, and running each of them exactly once.

A schedule row is claimed by one UPDATE of its own row inside a transaction: the
claim moves `next_run_at` past `now` and sets `last_run_at`, and only the worker
whose transaction does that runs the job. A second worker (the advisory lock keeps
that from happening, and this does not depend on it) either finds the row locked and
skips it, or reads it after the commit and finds it no longer due. So a due schedule
runs once, however many workers look at it and however often they look.

A schedule that was missed (the worker was down) runs once when the worker is back,
not once per missed time. A job is claimed before it runs: if the process dies
in the middle of a job, that run is lost and the next one is on time. For the jobs of
this application (a DNS check, reminders, a purge, a snapshot) that is the right
side to fail on, because every one of them is repeated by the next run.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import add_audit_event
from app.models import Schedule
from app.worker.cron import CronError, is_once, next_run_for

logger = logging.getLogger("revrook.worker")

DNS_CHECK = "dns-check"
EXPIRY_REMINDER = "expiry-reminder"
RETENTION_PURGE = "retention-purge"
SNAPSHOT_BUILD = "snapshot-build"
KINDS = (DNS_CHECK, EXPIRY_REMINDER, RETENTION_PURGE, SNAPSHOT_BUILD)
# The jobs of the whole installation (no client) and the jobs of one client.
GLOBAL_KINDS = (EXPIRY_REMINDER, RETENTION_PURGE)
CLIENT_KINDS = (DNS_CHECK, SNAPSHOT_BUILD)
# Created by the worker when they are missing: a reminder run every morning and the
# retention purge every night, both UTC.
DEFAULT_SCHEDULES = (
    ("expiry-reminders", EXPIRY_REMINDER, "0 6 * * *"),
    ("retention-purge", RETENTION_PURGE, "30 3 * * *"),
)
MAX_CLAIMED = 50
JOB_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class DueSchedule:
    """A schedule row that was claimed for this run."""

    id: int
    name: str
    kind: str
    client_id: int | None
    config: dict[str, Any]


Job = Callable[[DueSchedule, datetime], Awaitable[str]]


async def ensure_default_schedules(
    session_factory: async_sessionmaker[AsyncSession], now: datetime
) -> None:
    """Create the default schedules that do not exist yet (never touches a row)."""
    async with session_factory() as session, session.begin():
        for name, kind, cron in DEFAULT_SCHEDULES:
            await session.execute(
                insert(Schedule)
                .values(
                    name=name,
                    kind=kind,
                    cron=cron,
                    enabled=True,
                    next_run_at=next_run_for(cron, now),
                    config={},
                )
                .on_conflict_do_nothing(index_elements=[Schedule.name])
            )


def _claim(row: Schedule, now: datetime, session: AsyncSession) -> DueSchedule | None:
    """Move one due row forward. None when its expression cannot be read."""
    try:
        following = next_run_for(row.cron, now)
    except CronError:
        row.enabled = False
        add_audit_event(
            session,
            "schedule.disabled",
            target_type="schedule",
            target_id=row.id,
            detail={"reason": "the cron expression cannot be read"},
        )
        return None
    row.last_run_at = now
    row.next_run_at = following
    if is_once(row.cron):
        row.enabled = False
    return DueSchedule(row.id, row.name, row.kind, row.client_id, dict(row.config))


async def start_unscheduled(
    session_factory: async_sessionmaker[AsyncSession], now: datetime
) -> int:
    """Give a new enabled schedule its first run time. It does not run it now."""
    async with session_factory() as session, session.begin():
        found = await session.execute(
            select(Schedule)
            .where(Schedule.enabled.is_(True), Schedule.next_run_at.is_(None))
            .with_for_update(skip_locked=True)
        )
        started = 0
        for row in found.scalars():
            try:
                following = next_run_for(row.cron, now)
            except CronError:
                row.enabled = False
                continue
            # A one-time schedule without a time runs at the next look.
            row.next_run_at = now if following is None else following
            started += 1
        return started


async def claim_due(
    session_factory: async_sessionmaker[AsyncSession], now: datetime
) -> list[DueSchedule]:
    """Claim every schedule that is due at `now`. Each is returned to one caller."""
    async with session_factory() as session, session.begin():
        found = await session.execute(
            select(Schedule)
            .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at, Schedule.id)
            .limit(MAX_CLAIMED)
            .with_for_update(skip_locked=True)
        )
        claimed = [_claim(row, now, session) for row in found.scalars()]
    return [item for item in claimed if item is not None]


async def _record_failure(
    session_factory: async_sessionmaker[AsyncSession],
    due: DueSchedule,
    reason: str,
) -> None:
    async with session_factory() as session, session.begin():
        add_audit_event(
            session,
            "schedule.failed",
            target_type="schedule",
            target_id=due.id,
            detail={"kind": due.kind, "reason": reason},
        )


async def run_due(
    session_factory: async_sessionmaker[AsyncSession],
    jobs: dict[str, Job],
    now: datetime,
) -> dict[str, str]:
    """Run every schedule that is due at `now` once. Returns name to outcome.

    A job that fails is logged and audited; it never stops the others. The outcome
    of a failed job starts with `failed:`.
    """
    outcomes: dict[str, str] = {}
    for due in await claim_due(session_factory, now):
        job = jobs.get(due.kind)
        if job is None:
            outcomes[due.name] = "failed: unknown kind"
            await _record_failure(session_factory, due, "unknown kind")
            continue
        try:
            async with asyncio.timeout(JOB_TIMEOUT_SECONDS):
                outcomes[due.name] = await job(due, now)
        except Exception as error:
            # One bad job must not stop the worker; the class names what happened.
            reason = type(error).__name__
            logger.warning("schedule %s failed: %s", due.name, reason)
            outcomes[due.name] = f"failed: {reason}"
            await _record_failure(session_factory, due, reason)
        else:
            logger.info("schedule %s ran: %s", due.name, outcomes[due.name])
    return outcomes
