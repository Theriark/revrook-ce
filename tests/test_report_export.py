"""The export history: an immutable copy and the hash of every file that was made.

These tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.library import load_library
from app.evidence.files import FileStore, sha256_hex
from app.models import AuditEvent, ReportExport
from app.reports.completeness import ExportBlockedError
from app.reports.export import (
    ExportIntegrityError,
    ExportNotFoundError,
    ExportRecord,
    export_filename,
    export_report,
    list_exports,
    read_export,
)
from app.reports.render import INSURANCE, QBR, render_report
from app.reports.view import ReportView, build_view
from app.scoring.snapshot import parse_snapshot, render_snapshot
from app.settings import Settings
from helpers import create_test_client, make_context
from tools import report_clients

LIBRARY = load_library()


def view_of(name: str = "A", **context_changes: str) -> ReportView:
    context = replace(report_clients.context_for(name), **context_changes)
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        context,
        report_clients.previous_bytes(LIBRARY, name),
    )


def undated_view() -> ReportView:
    snapshot = parse_snapshot(report_clients.snapshot_bytes(LIBRARY, "A"))
    controls = tuple(
        replace(item, evidence_at=None) if item.control_id == "PC-ACC-01" else item
        for item in snapshot.controls
    )
    data = render_snapshot(replace(snapshot, controls=controls))
    return build_view(data, LIBRARY, report_clients.context_for("A"))


@pytest.fixture
def files(settings: Settings, tmp_path: Path) -> FileStore:
    return make_context(settings, tmp_path).files


async def export(
    engine: AsyncEngine, files: FileStore, client_id: int, kind: str = QBR
) -> tuple[ExportRecord, bytes]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        return await export_report(session, files, view_of(), kind, client_id=client_id)


async def test_an_export_keeps_an_immutable_copy_and_its_hash(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    record, data = await export(db_engine, ctx.files, client_id)
    assert data == render_report(QBR, view_of())
    assert record.sha256 == sha256_hex(data) and record.size_bytes == len(data)
    assert record.kind == QBR
    assert record.filename == "qbr-alder-and-finch-ltd-2026-10-17.html"
    assert ctx.files.read(record.storage_key) == data
    assert ctx.files.count_client_files(client_id) == 1
    async with async_sessionmaker(db_engine)() as session:
        stored = (await session.execute(select(ReportExport))).scalar_one()
        assert stored.file_sha256 == record.sha256
        assert stored.storage_key == record.storage_key
        audited = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "report.export",
                    AuditEvent.target_id == str(record.id),
                )
            )
        ).scalar_one()
        assert audited.detail["sha256"] == record.sha256


async def test_the_same_report_exported_twice_is_two_lines_and_one_file(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    first, _ = await export(db_engine, ctx.files, client_id)
    second, _ = await export(db_engine, ctx.files, client_id)
    assert first.sha256 == second.sha256 and first.id != second.id
    assert ctx.files.count_client_files(client_id) == 1
    async with async_sessionmaker(db_engine)() as session:
        history = await list_exports(session, client_id)
    assert [item.id for item in history] == [second.id, first.id]


async def test_an_incomplete_report_is_not_exported_and_leaves_nothing(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    with pytest.raises(ExportBlockedError) as caught:
        async with factory() as session, session.begin():
            await export_report(
                session, ctx.files, undated_view(), QBR, client_id=client_id
            )
    assert caught.value.problems == ("PC-ACC-01: a result with no dated evidence",)
    assert ctx.files.count_client_files(client_id) == 0
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(ReportExport))
    assert count == 0


async def test_an_unknown_kind_is_refused(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    with pytest.raises(ValueError, match="not a kind of report"):
        await export(db_engine, ctx.files, client_id, "deck")


async def test_a_stored_copy_is_read_back_after_a_check_of_its_hash(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    record, data = await export(db_engine, ctx.files, client_id, INSURANCE)
    async with async_sessionmaker(db_engine)() as session:
        again, copy = await read_export(session, ctx.files, client_id, record.id)
    assert copy == data and again == record
    path = ctx.files.root / record.storage_key
    path.write_bytes(data + b"<!-- changed -->")
    async with async_sessionmaker(db_engine)() as session:
        with pytest.raises(ExportIntegrityError, match="does not match"):
            await read_export(session, ctx.files, client_id, record.id)
    path.unlink()
    async with async_sessionmaker(db_engine)() as session:
        with pytest.raises(ExportIntegrityError, match="missing"):
            await read_export(session, ctx.files, client_id, record.id)
        with pytest.raises(ExportNotFoundError, match="no export"):
            await read_export(session, ctx.files, client_id, record.id + 1000)


@pytest.mark.parametrize(
    "assignment",
    [
        "file_sha256 = repeat('b', 64)",
        "size_bytes = 1",
        "filename = 'other.html'",
        "kind = 'insurance'",
        "storage_key = '1/aa/bb'",
        "exported_at = now() + interval '1 day'",
    ],
)
async def test_the_database_refuses_to_change_an_export(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path, assignment: str
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    record, _ = await export(db_engine, ctx.files, client_id)
    with pytest.raises(DBAPIError, match="immutable"):
        async with db_engine.begin() as connection:
            await connection.execute(
                text(f"UPDATE report_export SET {assignment} WHERE id = :id"),
                {"id": record.id},
            )
    async with async_sessionmaker(db_engine)() as session:
        stored = await session.get(ReportExport, record.id)
        assert stored is not None and stored.file_sha256 == record.sha256


async def test_a_link_can_still_be_cleared_when_its_target_is_deleted(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    record, _ = await export(db_engine, ctx.files, client_id)
    async with db_engine.begin() as connection:
        await connection.execute(
            text("UPDATE report_export SET snapshot_id = NULL WHERE id = :id"),
            {"id": record.id},
        )
        await connection.execute(
            text("DELETE FROM report_export WHERE id = :id"), {"id": record.id}
        )


def test_the_file_name_has_letters_digits_and_hyphens_only() -> None:
    hostile = view_of(client_name='<script>"../../etc/passwd"</script>')
    name = export_filename(QBR, hostile)
    assert name == "qbr-script-etc-passwd-script-2026-10-17.html"
    assert export_filename(INSURANCE, view_of(client_name="!!!")) == (
        "insurance-client-2026-10-17.html"
    )
    long_name = export_filename(QBR, view_of(client_name="a" * 150))
    assert long_name == f"qbr-{'a' * 40}-2026-10-17.html"
