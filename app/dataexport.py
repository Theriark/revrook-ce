"""The full data export: one zip with a CSV file per table, no personal identifiers.

The MSP can take its data out of revrook at any time. The zip holds what revrook
knows in a form a spreadsheet or a script can read: the clients, the evidence items
and revisions, the normalised facts, the snapshots and their control results, the
exception register, the export history, the schedules, the audit trail and the
evidence hash chain, plus `README.txt` and `manifest.csv` (the row count of each
file).

Left out on purpose, because a person could be named by it: user accounts, password
hashes, API tokens and the id of the user behind an audit event; the encrypted
pseudonym key of a client; the free text a person typed (reviewer names, notes, the
owner, reason and compensating control of an exception, the saved notes of a report)
and the kept files themselves. The facts are the pseudonymised values that were
stored at import, so a user principal name is not in them. A client's name is
included: it is the business the MSP serves and the only way to read the rest.

A cell that begins with `=`, `+`, `-`, `@`, a tab or a carriage return would be run
as a formula by a spreadsheet. Such a text cell gets a leading apostrophe.

The export is built as a stream: each table is read from a server-side cursor and
written to the zip through a buffer of CHUNK_BYTES, into a temporary file that stays
in memory up to SPOOL_BYTES and goes to disk beyond that. Memory use is therefore
about SPOOL_BYTES plus one chunk whatever the size of the data. The CSV text of one
export is capped at MAX_EXPORT_BYTES (256 MiB, before compression); an installation
with more is refused with 413 and takes a database backup instead.
"""

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from tempfile import SpooledTemporaryFile
from typing import IO, Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.errors import EvidenceTooLargeError
from app.models import (
    AuditEvent,
    Client,
    ControlResult,
    EvidenceItem,
    EvidenceLog,
    EvidenceRevision,
    ExceptionRecord,
    Fact,
    ReportExport,
    Schedule,
    Snapshot,
)

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
MEBIBYTE = 1024 * 1024
MAX_EXPORT_BYTES = 256 * MEBIBYTE
SPOOL_BYTES = 8 * MEBIBYTE
CHUNK_BYTES = 64 * 1024
README = """revrook data export

Generated at {generated} by revrook {version}.

One CSV file per table, UTF-8, with a header row. manifest.csv lists the number of
rows of each file. Times are ISO 8601 in UTC. A column called value, detail, inputs
or payload holds JSON.

Not in this export, because a person could be named by it: user accounts, password
hashes, API tokens, the user behind an audit event, the encrypted pseudonym key of a
client, free text typed by a person (reviewer, notes, exception owner, reason and
compensating control, saved report notes) and the kept files. The facts hold the
pseudonymised values stored at import. The client name is included.

A text cell that began with =, +, - or @ has a leading apostrophe so that a
spreadsheet does not run it as a formula.
"""


def export_tables() -> list[tuple[str, Select[Any]]]:
    """The tables of the export and the query that reads each one."""
    return [
        (
            "clients",
            select(
                Client.id,
                Client.name,
                Client.created_at,
                Client.archived_at,
            ).order_by(Client.id),
        ),
        (
            "evidence_items",
            select(
                EvidenceItem.id,
                EvidenceItem.client_id,
                EvidenceItem.source_code,
                EvidenceItem.captured_at,
                EvidenceItem.imported_at,
                EvidenceItem.sha256,
                EvidenceItem.size_bytes,
                EvidenceItem.importer_version,
                EvidenceItem.ruleset_version,
                EvidenceItem.assurance_level,
                EvidenceItem.status,
                EvidenceItem.expires_at,
            ).order_by(EvidenceItem.id),
        ),
        (
            "evidence_revisions",
            select(
                EvidenceRevision.id,
                EvidenceRevision.item_id,
                EvidenceRevision.revision_number,
                EvidenceRevision.supersedes_id,
                EvidenceRevision.sha256,
                EvidenceRevision.size_bytes,
                EvidenceRevision.storage_key.is_not(None).label("raw_file_kept"),
                EvidenceRevision.raw_expires_at,
                EvidenceRevision.created_at,
            ).order_by(EvidenceRevision.id),
        ),
        (
            "facts",
            select(
                Fact.id,
                Fact.client_id,
                Fact.evidence_item_id,
                Fact.fact_key,
                Fact.value,
                Fact.captured_at,
            ).order_by(Fact.id),
        ),
        (
            "snapshots",
            select(
                Snapshot.id,
                Snapshot.client_id,
                Snapshot.period_start,
                Snapshot.period_end,
                Snapshot.as_of,
                Snapshot.ruleset_version,
                Snapshot.created_at,
                Snapshot.inputs,
            ).order_by(Snapshot.id),
        ),
        (
            "control_results",
            select(
                ControlResult.id,
                ControlResult.snapshot_id,
                ControlResult.control_id,
                ControlResult.status,
                ControlResult.numerator,
                ControlResult.denominator,
                ControlResult.detail,
            ).order_by(ControlResult.id),
        ),
        (
            "exceptions",
            select(
                ExceptionRecord.id,
                ExceptionRecord.client_id,
                ExceptionRecord.control_id,
                ExceptionRecord.review_date,
                ExceptionRecord.created_at,
                ExceptionRecord.closed_at,
            ).order_by(ExceptionRecord.id),
        ),
        (
            "report_exports",
            select(
                ReportExport.id,
                ReportExport.client_id,
                ReportExport.snapshot_id,
                ReportExport.kind,
                ReportExport.filename,
                ReportExport.file_sha256,
                ReportExport.size_bytes,
                ReportExport.exported_at,
            ).order_by(ReportExport.id),
        ),
        (
            "schedules",
            select(
                Schedule.id,
                Schedule.name,
                Schedule.kind,
                Schedule.cron,
                Schedule.enabled,
                Schedule.client_id,
                Schedule.last_run_at,
                Schedule.next_run_at,
            ).order_by(Schedule.id),
        ),
        (
            "audit_events",
            select(
                AuditEvent.id,
                AuditEvent.occurred_at,
                AuditEvent.action,
                AuditEvent.target_type,
                AuditEvent.target_id,
                AuditEvent.detail,
            ).order_by(AuditEvent.id),
        ),
        (
            "evidence_log",
            select(
                EvidenceLog.id,
                EvidenceLog.client_id,
                EvidenceLog.evidence_item_id,
                EvidenceLog.event_type,
                EvidenceLog.payload,
                EvidenceLog.previous_hash,
                EvidenceLog.record_hash,
                EvidenceLog.created_at,
            ).order_by(EvidenceLog.id),
        ),
    ]


def cell(value: object) -> str:
    """One value as the text of a CSV cell, safe against a spreadsheet formula."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    text = str(value)
    if text.startswith(FORMULA_STARTS):
        return "'" + text
    return text


class ExportTooLargeError(EvidenceTooLargeError):
    """The export would hold more than MAX_EXPORT_BYTES of CSV text."""


@dataclass
class _Budget:
    """The CSV bytes written so far, against the most one export may hold."""

    limit: int
    spent: int = 0

    def spend(self, size: int) -> None:
        self.spent += size
        if self.spent > self.limit:
            raise ExportTooLargeError(
                f"The export would hold more than {self.limit / MEBIBYTE:g} MiB of "
                "data. Take a database backup instead (see docs/operations.md)."
            )


def _flush(buffer: io.StringIO, entry: IO[bytes], budget: _Budget) -> None:
    """Write what the buffer holds to the zip entry and empty the buffer."""
    data = buffer.getvalue().encode("utf-8")
    budget.spend(len(data))
    entry.write(data)
    buffer.seek(0)
    buffer.truncate(0)


async def _write_table(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    name: str,
    query: Select[Any],
    now: datetime,
    budget: _Budget,
) -> int:
    """Stream one query into the zip as a CSV file; returns its number of rows.

    Rows are read from a server-side cursor and written out every CHUNK_BYTES, so
    the memory held is one chunk and not the table.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(list(query.selected_columns.keys()))
    rows = 0
    result = await session.stream(query)
    with archive.open(_entry(f"{name}.csv", now), "w") as entry:
        async for row in result:
            writer.writerow([cell(value) for value in row])
            rows += 1
            if buffer.tell() >= CHUNK_BYTES:
                _flush(buffer, entry, budget)
        _flush(buffer, entry, budget)
    return rows


def _entry(name: str, moment: datetime) -> zipfile.ZipInfo:
    stamp = moment.timetuple()[:6]
    info = zipfile.ZipInfo(name, date_time=stamp)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


async def build_export(
    session: AsyncSession,
    now: datetime,
    version: str,
    max_bytes: int = MAX_EXPORT_BYTES,
) -> tuple[SpooledTemporaryFile[bytes], dict[str, int]]:
    """The zip, as a file positioned at its start, and the rows of each table.

    The zip is built as it is read: every table is streamed through a small buffer
    into a temporary file that stays in memory up to SPOOL_BYTES and then goes to
    disk. The caller closes the file. The CSV text of the whole export is capped at
    `max_bytes` (MAX_EXPORT_BYTES); past it ExportTooLargeError is raised and
    nothing is kept.

    `now` must not be earlier than 1980, the oldest date a zip file can hold.
    """
    output: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(max_size=SPOOL_BYTES)
    budget = _Budget(max_bytes)
    counts: dict[str, int] = {}
    try:
        with zipfile.ZipFile(output, "w") as archive:
            for name, query in export_tables():
                counts[name] = await _write_table(
                    session, archive, name, query, now, budget
                )
            manifest = io.StringIO(newline="")
            writer = csv.writer(manifest, lineterminator="\r\n")
            writer.writerow(["file", "rows"])
            for name, rows in counts.items():
                writer.writerow([f"{name}.csv", rows])
            archive.writestr(_entry("manifest.csv", now), manifest.getvalue())
            readme = README.format(generated=now.isoformat(), version=version)
            archive.writestr(_entry("README.txt", now), readme)
    except BaseException:
        output.close()
        raise
    output.seek(0)
    return output, counts


def file_size(file: SpooledTemporaryFile[bytes]) -> int:
    """The size of a file in bytes; the position goes back to the start."""
    file.seek(0, io.SEEK_END)
    size = file.tell()
    file.seek(0)
    return size
