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
"""

import csv
import io
import json
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _table_csv(session: AsyncSession, query: Select[Any]) -> tuple[bytes, int]:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(list(query.selected_columns.keys()))
    rows = 0
    result = await session.stream(query)
    async for row in result:
        writer.writerow([cell(value) for value in row])
        rows += 1
    return buffer.getvalue().encode("utf-8"), rows


def _entry(name: str, moment: datetime) -> zipfile.ZipInfo:
    stamp = moment.timetuple()[:6]
    info = zipfile.ZipInfo(name, date_time=stamp)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


async def build_export(
    session: AsyncSession, now: datetime, version: str
) -> tuple[bytes, dict[str, int]]:
    """The zip and the number of rows of each table.

    `now` must not be earlier than 1980, the oldest date a zip file can hold.
    """
    output = io.BytesIO()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(output, "w") as archive:
        for name, query in export_tables():
            data, rows = await _table_csv(session, query)
            archive.writestr(_entry(f"{name}.csv", now), data)
            counts[name] = rows
        manifest = io.StringIO(newline="")
        writer = csv.writer(manifest, lineterminator="\r\n")
        writer.writerow(["file", "rows"])
        for name, rows in counts.items():
            writer.writerow([f"{name}.csv", rows])
        archive.writestr(_entry("manifest.csv", now), manifest.getvalue())
        readme = README.format(generated=now.isoformat(), version=version)
        archive.writestr(_entry("README.txt", now), readme)
    return output.getvalue(), counts
