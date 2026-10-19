"""The retention purge: what leaves the instance when its time is up.

Three things expire, each with its own rule, and every removal is an audit event.

* A raw file (only kept when RAW_RETENTION_DAYS is above zero) goes when its
  `raw_expires_at` has passed: `purge_expired_raw` of the evidence package, which
  also writes the chain record. Its hash stays.
* A pack, meaning a stored snapshot or an exported report, goes PACK_RETENTION_MONTHS
  months after it was made (default 25). The row is deleted, and so is the kept copy
  of an export unless another row still points at the same file.
* A folder of files whose client no longer exists (a deletion that stopped half way)
  is removed.

Only rows past their date are touched. Evidence items, facts, the hash chain and the
audit trail are never purged here: they go with their client, and only then.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import add_audit_event
from app.evidence.deletion import remove_leftover_files
from app.evidence.errors import EvidenceStorageError
from app.evidence.expiry import add_months
from app.evidence.files import FileStore
from app.evidence.retention import PURGE_BATCH_SIZE, purge_expired_raw
from app.models import EvidenceRevision, ReportExport, Schedule, Snapshot
from app.worker.cron import ONCE

logger = logging.getLogger("revrook.worker")

# A full batch is followed by another one; this stops a run that cannot make progress.
MAX_BATCHES = 100
# A one-time schedule (a snapshot request) is kept this long after it ran.
FINISHED_REQUEST_KEPT = timedelta(days=7)


@dataclass(frozen=True)
class PurgeResult:
    """What one purge removed. Counts only."""

    raw_files: int = 0
    snapshots: int = 0
    exports: int = 0
    leftover_folders: int = 0
    finished_requests: int = 0

    @property
    def total(self) -> int:
        return (
            self.raw_files
            + self.snapshots
            + self.exports
            + self.leftover_folders
            + self.finished_requests
        )

    def summary(self) -> str:
        return (
            f"{self.raw_files} raw files, {self.snapshots} snapshots, "
            f"{self.exports} exports, {self.leftover_folders} leftover folders, "
            f"{self.finished_requests} finished requests"
        )


async def purge_raw(
    session_factory: async_sessionmaker[AsyncSession],
    files: FileStore,
    now: datetime,
) -> int:
    """Delete every raw file past its date, one batch per transaction."""
    removed = 0
    for _ in range(MAX_BATCHES):
        async with session_factory() as session, session.begin():
            batch = await purge_expired_raw(session, files, now)
        removed += batch
        if batch < PURGE_BATCH_SIZE:
            break
    return removed


async def _still_used(session: AsyncSession, key: str) -> bool:
    """Whether a row of an export or of an evidence revision points at the file."""
    exports = (
        select(func.count())
        .select_from(ReportExport)
        .where(ReportExport.storage_key == key)
    )
    revisions = (
        select(func.count())
        .select_from(EvidenceRevision)
        .where(EvidenceRevision.storage_key == key)
    )
    count = (await session.execute(exports)).scalar_one()
    count += (await session.execute(revisions)).scalar_one()
    return bool(count)


async def purge_exports(
    session_factory: async_sessionmaker[AsyncSession],
    files: FileStore,
    cutoff: datetime,
) -> int:
    """Delete the exports made at or before the cutoff, and their kept copies."""
    removable: list[str] = []
    async with session_factory() as session, session.begin():
        found = await session.execute(
            select(
                ReportExport.id,
                ReportExport.client_id,
                ReportExport.kind,
                ReportExport.file_sha256,
                ReportExport.storage_key,
            )
            .where(ReportExport.exported_at <= cutoff)
            .order_by(ReportExport.id)
            .limit(PURGE_BATCH_SIZE)
        )
        rows = found.all()
        if not rows:
            return 0
        ids = [row.id for row in rows]
        await session.execute(delete(ReportExport).where(ReportExport.id.in_(ids)))
        for row in rows:
            add_audit_event(
                session,
                "export.purged",
                target_type="report_export",
                target_id=row.id,
                detail={
                    "client_id": row.client_id,
                    "kind": row.kind,
                    "sha256": row.file_sha256,
                },
            )
        for key in sorted({row.storage_key for row in rows}):
            if not await _still_used(session, key):
                removable.append(key)
    for key in removable:
        try:
            await asyncio.to_thread(files.remove, key)
        except EvidenceStorageError:
            logger.warning("a purged export copy could not be removed")
    return len(rows)


async def purge_snapshots(
    session_factory: async_sessionmaker[AsyncSession], cutoff: datetime
) -> int:
    """Delete the snapshots made at or before the cutoff, with their results."""
    async with session_factory() as session, session.begin():
        found = await session.execute(
            select(Snapshot.id, Snapshot.client_id, Snapshot.period_end)
            .where(Snapshot.created_at <= cutoff)
            .order_by(Snapshot.id)
            .limit(PURGE_BATCH_SIZE)
        )
        rows = found.all()
        if not rows:
            return 0
        await session.execute(
            delete(Snapshot).where(Snapshot.id.in_([row.id for row in rows]))
        )
        for row in rows:
            add_audit_event(
                session,
                "snapshot.purged",
                target_type="snapshot",
                target_id=row.id,
                detail={
                    "client_id": row.client_id,
                    "period_end": row.period_end.isoformat(),
                },
            )
    return len(rows)


async def purge_leftovers(
    session_factory: async_sessionmaker[AsyncSession], files: FileStore
) -> int:
    """Remove the file folders of clients that are gone, and audit each one."""
    async with session_factory() as session, session.begin():
        removed = await remove_leftover_files(session, files)
        for client_id in removed:
            add_audit_event(
                session,
                "files.leftover_removed",
                target_type="client",
                target_id=client_id,
            )
    return len(removed)


async def purge_finished_requests(
    session_factory: async_sessionmaker[AsyncSession], now: datetime
) -> int:
    """Delete one-time schedules (snapshot requests) that ran a week ago or more."""
    cutoff = now - FINISHED_REQUEST_KEPT
    async with session_factory() as session, session.begin():
        result = await session.execute(
            delete(Schedule)
            .where(
                Schedule.cron == ONCE,
                Schedule.enabled.is_(False),
                Schedule.last_run_at <= cutoff,
            )
            .returning(Schedule.id)
        )
        return len(result.all())


async def run_purge(
    session_factory: async_sessionmaker[AsyncSession],
    files: FileStore,
    now: datetime,
    pack_retention_months: int,
) -> PurgeResult:
    """One retention run. The pack cutoff is `pack_retention_months` before `now`."""
    cutoff = add_months(now, -pack_retention_months)
    result = PurgeResult(
        raw_files=await purge_raw(session_factory, files, now),
        exports=await purge_exports(session_factory, files, cutoff),
        snapshots=await purge_snapshots(session_factory, cutoff),
        leftover_folders=await purge_leftovers(session_factory, files),
        finished_requests=await purge_finished_requests(session_factory, now),
    )
    if result.total:
        async with session_factory() as session, session.begin():
            add_audit_event(
                session,
                "retention.run",
                detail={
                    "raw_files": result.raw_files,
                    "snapshots": result.snapshots,
                    "exports": result.exports,
                    "leftover_folders": result.leftover_folders,
                    "finished_requests": result.finished_requests,
                },
            )
    return result
