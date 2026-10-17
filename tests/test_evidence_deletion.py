"""Delete-per-client: everything of the client goes, the audit trail stays."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.assurance import Assurance
from app.evidence.chain import chained_client_ids, verify_all, verify_chain
from app.evidence.deletion import DeletionReport, delete_client, remove_leftover_files
from app.evidence.errors import (
    ClientNotFoundError,
    EvidenceRejectedError,
    EvidenceStorageError,
)
from app.evidence.files import FileStore
from app.evidence.service import EvidenceContext, NewEvidence
from app.models import EvidenceLog
from app.settings import Settings
from helpers import (
    NOW,
    SYNTHETIC_USERS,
    audit_baseline,
    audit_since,
    create_test_client,
    database_dump,
    export_evidence,
    make_context,
    scalar,
    upload,
)

CLIENT_NAME = "Synthetic Client Ltd"
INSERT_SNAPSHOT = text(
    "INSERT INTO snapshot (client_id, period_start, period_end, as_of, "
    "ruleset_version, importer_versions, inputs) VALUES (:client, "
    "DATE '2026-07-01', DATE '2026-09-30', now(), '1.0.0', "
    "CAST('{}' AS jsonb), CAST('{}' AS jsonb)) RETURNING id"
)
OTHER_INSERTS = (
    "INSERT INTO control_result (snapshot_id, control_id, status) "
    "VALUES (:snapshot, 'PC-ACC-01', 'pass')",
    "INSERT INTO report_export (client_id, snapshot_id, kind, filename, "
    "file_sha256, size_bytes, storage_key) VALUES (:client, :snapshot, 'qbr', "
    "'report.pdf', repeat('a', 64), 10, 'exports/report.pdf')",
    "INSERT INTO exception_record (client_id, control_id, owner, reason, "
    "review_date) VALUES (:client, 'PC-ACC-01', 'Sam', 'Accepted', "
    "DATE '2026-12-01')",
    "INSERT INTO import_profile (client_id, name, source_code, mapping) "
    "VALUES (:client, 'vendor file', 'reference-csv', CAST('{}' AS jsonb))",
    "INSERT INTO schedule (name, kind, cron, client_id) "
    "VALUES ('nightly-check', 'dns-check', '0 3 * * *', :client)",
)
# Rows left in each table once the first client is deleted: only the survivor.
REMAINING_ROWS = {
    "client": 1,
    "evidence_item": 1,
    "evidence_revision": 1,
    "fact": 4,
    "snapshot": 0,
    "control_result": 0,
    "report_export": 0,
    "exception_record": 0,
    "import_profile": 0,
    "schedule": 0,
}


def manual() -> NewEvidence:
    return NewEvidence(
        source_code="restore-test",
        assurance=Assurance.MANUAL_ARTEFACT,
        captured_at=NOW - timedelta(days=10),
        data=b"%PDF-1.4 synthetic restore test",
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, 1),
        note="Restore test of the file server",
    )


def attestation() -> NewEvidence:
    return NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=NOW - timedelta(days=3),
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, 1),
        note="Staff training was completed",
    )


async def fill_other_tables(engine: AsyncEngine, client_id: int) -> None:
    """One snapshot, control result, export, exception, profile and schedule."""
    async with engine.begin() as connection:
        result = await connection.execute(INSERT_SNAPSHOT, {"client": client_id})
        snapshot_id = result.scalar_one()
        for statement in OTHER_INSERTS:
            await connection.execute(
                text(statement), {"client": client_id, "snapshot": snapshot_id}
            )


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(settings, tmp_path, raw_retention_days=7)


async def delete(
    engine: AsyncEngine, ctx: EvidenceContext, client_id: int, confirm: str
) -> DeletionReport:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return await delete_client(
        factory,
        ctx.files,
        client_id,
        confirm_name=confirm,
        actor_user_id=None,
        now=NOW,
    )


async def test_deleting_a_client_removes_everything_and_leaves_the_audit_trail(
    db_engine: AsyncEngine, ctx: EvidenceContext, tmp_path: Path
) -> None:
    client_id = await create_test_client(db_engine, ctx, CLIENT_NAME)
    survivor = await create_test_client(db_engine, ctx, "Survivor Ltd")
    await upload(db_engine, ctx, client_id, export_evidence())
    await upload(db_engine, ctx, client_id, manual())
    await upload(db_engine, ctx, client_id, attestation())
    await upload(db_engine, ctx, survivor, export_evidence())
    await fill_other_tables(db_engine, client_id)
    assert ctx.files.count_client_files(client_id) == 2
    baseline = await audit_baseline(db_engine)

    report = await delete(db_engine, ctx, client_id, f"  {CLIENT_NAME} ")

    counts = {"items": 3, "revisions": 3, "facts": 4, "packs": 2, "files": 2}
    assert report == DeletionReport(client_id=client_id, **counts)

    # Every row and file of the client is gone, and so is its key.
    query = "SELECT count(*) FROM client WHERE id = :client"
    assert await scalar(db_engine, query, client=client_id) == 0
    for table, expected in REMAINING_ROWS.items():
        remaining = await scalar(db_engine, f"SELECT count(*) FROM {table}")
        assert remaining == expected, table
    assert ctx.files.count_client_files(client_id) == 0
    assert not (tmp_path / str(client_id)).exists()
    dump = await database_dump(db_engine)
    for upn, _ in SYNTHETIC_USERS:
        assert upn not in dump
    for removed in (CLIENT_NAME, "Sam Reviewer", "Staff training", "Restore test"):
        assert removed not in dump

    # Only the append-only audit trail remains, and it holds counts, not content.
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["client.deleted"]
    assert events[0].target_type == "client"
    assert events[0].target_id == str(client_id)
    assert events[0].detail == counts

    async with async_sessionmaker(db_engine)() as session:
        log = select(EvidenceLog).where(EvidenceLog.client_id == client_id)
        found = await session.execute(log.order_by(EvidenceLog.id))
        records = list(found.scalars())
        assert [record.event_type for record in records] == [
            "evidence.added",
            "evidence.added",
            "evidence.added",
            "client.deleted",
        ]
        assert records[-1].payload == counts
        result = await verify_chain(session, client_id)
        assert (result.ok, result.records) == (True, 4)
        assert client_id in await chained_client_ids(session)
        assert all(chain.ok for chain in await verify_all(session))

    # The other client is untouched.
    assert ctx.files.count_client_files(survivor) == 1


async def test_a_wrong_confirmation_deletes_nothing(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx, CLIENT_NAME)
    await upload(db_engine, ctx, client_id, export_evidence())
    baseline = await audit_baseline(db_engine)
    for wrong in ("", "synthetic client ltd", "Another Client"):
        with pytest.raises(EvidenceRejectedError, match="confirmation does not match"):
            await delete(db_engine, ctx, client_id, wrong)
    assert await scalar(db_engine, "SELECT count(*) FROM client") == 1
    assert ctx.files.count_client_files(client_id) == 1
    assert await audit_since(db_engine, baseline) == []


async def test_deleting_an_unknown_client_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    with pytest.raises(ClientNotFoundError):
        await delete(db_engine, ctx, 987_654_321, CLIENT_NAME)


async def test_files_left_behind_by_a_failed_removal_can_be_swept(
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = await create_test_client(db_engine, ctx, CLIENT_NAME)
    await upload(db_engine, ctx, client_id, export_evidence())

    def refuse(client: int) -> int:
        raise EvidenceStorageError("the files of the client could not be removed")

    monkeypatch.setattr(ctx.files, "remove_client", refuse)
    with pytest.raises(EvidenceStorageError):
        await delete(db_engine, ctx, client_id, CLIENT_NAME)
    # The database part had committed: the client is gone, its folder is not.
    assert await scalar(db_engine, "SELECT count(*) FROM client") == 0
    assert (tmp_path / str(client_id)).exists()

    async with async_sessionmaker(db_engine)() as session:
        removed = await remove_leftover_files(session, FileStore(tmp_path))
    assert removed == [client_id]
    assert not (tmp_path / str(client_id)).exists()


async def test_the_sweep_keeps_the_folders_of_clients_that_exist(
    db_engine: AsyncEngine, ctx: EvidenceContext, tmp_path: Path
) -> None:
    store = FileStore(tmp_path)
    async with async_sessionmaker(db_engine)() as session:
        assert await remove_leftover_files(session, store) == []
    live = await create_test_client(db_engine, ctx)
    await upload(db_engine, ctx, live, export_evidence())
    store.put(424_242, b"orphan")
    async with async_sessionmaker(db_engine)() as session:
        assert await remove_leftover_files(session, store) == [424_242]
        assert await remove_leftover_files(session, store) == []
    assert store.count_client_files(live) == 1
