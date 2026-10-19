"""The export history: an immutable copy and the hash of every report that was made.

`export_report` is the one way a report leaves the instance. It runs the completeness
check (an unsupported claim blocks the export), renders the HTML, keeps a copy in the
evidence store under its own SHA-256 (a file that is named by its hash cannot be
changed without changing its name) and writes one `report_export` row with the hash,
the size and the key. The row cannot be changed afterwards (the database refuses an
update of its file columns, see migration 0004) and `read_export` checks the copy
against the stored hash every time it is read, so a copy that was altered on disk is
reported, never sent.

The copy is what was sent. Nothing is rendered again to answer a download.

An export takes the client's row lock before it writes anything (the same lock
delete-per-client takes), so a client that is being deleted is waited for and the
export then fails with ClientNotFoundError: no file is left behind without a row. A
download names the client, and an export of another client is "not found".
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.evidence.errors import EvidenceError, EvidenceStorageError
from app.evidence.files import FileStore, sha256_hex
from app.evidence.locking import lock_client
from app.models import ReportExport
from app.reports.completeness import ensure_complete
from app.reports.render import KINDS, render_report
from app.reports.view import ReportView, iso_date

MAX_SLUG = 40


class ExportIntegrityError(EvidenceError):
    """The stored copy of an export is missing or does not match its hash."""


class ExportNotFoundError(EvidenceError):
    """There is no export with this id for this client."""


@dataclass(frozen=True)
class ExportRecord:
    """One line of the export history."""

    id: int
    client_id: int
    snapshot_id: int | None
    kind: str
    filename: str
    sha256: str
    size_bytes: int
    storage_key: str
    exported_at: datetime
    exported_by_id: int | None = None


def _record(row: ReportExport) -> ExportRecord:
    return ExportRecord(
        id=row.id,
        client_id=row.client_id,
        snapshot_id=row.snapshot_id,
        kind=row.kind,
        filename=row.filename,
        sha256=row.file_sha256,
        size_bytes=row.size_bytes,
        storage_key=row.storage_key,
        exported_at=row.exported_at,
        exported_by_id=row.exported_by_id,
    )


def export_filename(kind: str, view: ReportView) -> str:
    """A file name of letters, digits and hyphens, whatever the client is called."""
    slug = re.sub(r"[^a-z0-9]+", "-", view.context.client_name.lower().strip())
    slug = slug.strip("-")[:MAX_SLUG].strip("-") or "client"
    return f"{kind}-{slug}-{iso_date(view.snapshot.as_of)}.html"


async def export_report(
    session: AsyncSession,
    files: FileStore,
    view: ReportView,
    kind: str,
    *,
    client_id: int,
    snapshot_id: int | None = None,
    user_id: int | None = None,
) -> tuple[ExportRecord, bytes]:
    """Check, render and record one report. Returns the history line and the file.

    Raises ExportBlockedError (with every problem named) when the report claims more
    than its evidence shows, ValueError for an unknown kind, ClientNotFoundError when
    the client is gone and EvidenceStorageError when the copy cannot be written
    (nothing is recorded then). The caller's transaction holds the row, so a rolled
    back export leaves no history line (the copy is named by its hash and harmless on
    its own). The client's row lock is held from here to the end of that transaction.
    """
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not a kind of report; use one of {KINDS}")
    await lock_client(session, client_id)
    ensure_complete(view)
    data = render_report(kind, view)
    digest = sha256_hex(data)
    key = await asyncio.to_thread(files.put, client_id, data)
    row = ReportExport(
        client_id=client_id,
        snapshot_id=snapshot_id,
        kind=kind,
        filename=export_filename(kind, view),
        file_sha256=digest,
        size_bytes=len(data),
        storage_key=key,
        exported_by_id=user_id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    add_audit_event(
        session,
        "report.export",
        actor_user_id=user_id,
        target_type="report_export",
        target_id=row.id,
        detail={"kind": kind, "sha256": digest, "size_bytes": len(data)},
    )
    return _record(row), data


async def list_exports(session: AsyncSession, client_id: int) -> list[ExportRecord]:
    """The export history of one client, newest first."""
    rows = await session.execute(
        select(ReportExport)
        .where(ReportExport.client_id == client_id)
        .order_by(ReportExport.exported_at.desc(), ReportExport.id.desc())
    )
    return [_record(row) for row in rows.scalars()]


async def read_export(
    session: AsyncSession, files: FileStore, client_id: int, export_id: int
) -> tuple[ExportRecord, bytes]:
    """The history line and the stored copy, after checking the copy against its hash.

    Raises ExportNotFoundError when this client has no such export (an export of
    another client is not found either) and ExportIntegrityError when the copy is
    missing or the bytes do not hash to the recorded value.
    """
    row = await session.get(ReportExport, export_id)
    if row is None or row.client_id != client_id:
        raise ExportNotFoundError("There is no export with this id for this client.")
    try:
        data = await asyncio.to_thread(files.read, row.storage_key)
    except EvidenceStorageError:
        raise ExportIntegrityError(
            "The stored copy of this export is missing."
        ) from None
    if sha256_hex(data) != row.file_sha256 or len(data) != row.size_bytes:
        raise ExportIntegrityError(
            "The stored copy of this export does not match its recorded hash."
        )
    return _record(row), data
