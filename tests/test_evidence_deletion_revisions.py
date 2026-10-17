"""Phase 2 carry-over (F3): deleting a client whose item has two revisions."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.assurance import Assurance
from app.evidence.chain import verify_chain
from app.evidence.deletion import DeletionReport, delete_client
from app.evidence.service import EvidenceContext, NewEvidence, add_revision
from app.settings import Settings
from helpers import NOW, create_test_client, database_dump, make_context, scalar, upload

CLIENT_NAME = "Synthetic Client Ltd"
FIRST = b"%PDF-1.4 first restore test"
SECOND = b"%PDF-1.4 second restore test"


def manual(data: bytes, day: int) -> NewEvidence:
    return NewEvidence(
        source_code="restore-test",
        assurance=Assurance.MANUAL_ARTEFACT,
        captured_at=NOW - timedelta(days=12 - day),
        data=data,
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, day),
        note=f"Restore test {day}",
    )


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(settings, tmp_path)


async def test_deleting_a_client_whose_item_has_two_revisions_removes_both(
    db_engine: AsyncEngine, ctx: EvidenceContext, tmp_path: Path
) -> None:
    client_id = await create_test_client(db_engine, ctx, CLIENT_NAME)
    first = await upload(db_engine, ctx, client_id, manual(FIRST, 1))
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        second = await add_revision(
            session, ctx, client_id, first.item_id, manual(SECOND, 10), NOW
        )
    assert second.revision_number == 2
    assert ctx.files.count_client_files(client_id) == 2

    report = await delete_client(
        factory,
        ctx.files,
        client_id,
        confirm_name=CLIENT_NAME,
        actor_user_id=None,
        now=NOW,
    )

    counts = {"items": 1, "revisions": 2, "facts": 0, "packs": 0, "files": 2}
    assert report == DeletionReport(client_id=client_id, **counts)
    for table in ("client", "evidence_item", "evidence_revision"):
        assert await scalar(db_engine, f"SELECT count(*) FROM {table}") == 0, table
    assert ctx.files.count_client_files(client_id) == 0
    assert not (tmp_path / str(client_id)).exists()
    dump = await database_dump(db_engine)
    for removed in (CLIENT_NAME, "Sam Reviewer", "Restore test"):
        assert removed not in dump
    async with async_sessionmaker(db_engine)() as session:
        result = await verify_chain(session, client_id)
    assert (result.ok, result.records) == (True, 3)
