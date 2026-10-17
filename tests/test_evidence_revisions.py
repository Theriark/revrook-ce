"""Evidence revisions: a correction is a new revision, the old one never changes."""

import hashlib
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Select, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.assurance import Assurance
from app.evidence.chain import verify_chain
from app.evidence.errors import (
    ClientNotFoundError,
    DuplicateEvidenceError,
    EvidenceRejectedError,
    ItemNotFoundError,
)
from app.evidence.service import (
    EvidenceContext,
    NewEvidence,
    StoredEvidence,
    add_revision,
    list_evidence,
)
from app.models import EvidenceItem, EvidenceLog, EvidenceRevision
from app.settings import Settings
from helpers import (
    NOW,
    audit_baseline,
    audit_since,
    create_test_client,
    export_evidence,
    make_context,
    upload,
)

FIRST = b"%PDF-1.4 first restore test"
SECOND = b"%PDF-1.4 second restore test"


def manual(data: bytes, reviewer: str = "Sam Reviewer", day: int = 1) -> NewEvidence:
    return NewEvidence(
        source_code="restore-test",
        assurance=Assurance.MANUAL_ARTEFACT,
        captured_at=NOW - timedelta(days=12 - day),
        data=data,
        reviewer=reviewer,
        reviewed_on=date(2026, 10, day),
        note=f"Restore test {day}",
    )


def statement(day: int = 1) -> NewEvidence:
    return NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=NOW - timedelta(days=12 - day),
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, day),
        note="Staff training was completed",
    )


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(settings, tmp_path)


async def revise(
    engine: AsyncEngine,
    ctx: EvidenceContext,
    client_id: int,
    item_id: int,
    evidence: NewEvidence,
) -> StoredEvidence:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        return await add_revision(session, ctx, client_id, item_id, evidence, NOW)


async def load(engine: AsyncEngine, query: Select[Any]) -> list[Any]:
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(query)).scalars())


async def revisions_of(engine: AsyncEngine, item_id: int) -> list[EvidenceRevision]:
    query = select(EvidenceRevision).where(EvidenceRevision.item_id == item_id)
    return await load(engine, query.order_by(EvidenceRevision.revision_number))


async def test_a_revision_supersedes_the_one_before_and_leaves_it_as_it_was(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    first = await upload(db_engine, ctx, client_id, manual(FIRST))
    baseline = await audit_baseline(db_engine)
    newer = manual(SECOND, "Alex Reviewer", 10)
    second = await revise(db_engine, ctx, client_id, first.item_id, newer)

    assert (second.item_id, second.revision_number) == (first.item_id, 2)
    first_row, second_row = await revisions_of(db_engine, first.item_id)
    assert first_row.sha256 == hashlib.sha256(FIRST).hexdigest()
    assert first_row.reviewer == "Sam Reviewer"
    assert first_row.reviewed_on == date(2026, 10, 1)
    assert first_row.supersedes_id is None
    assert second_row.supersedes_id == first_row.id
    assert second_row.sha256 == hashlib.sha256(SECOND).hexdigest()
    assert second_row.reviewer == "Alex Reviewer"

    (item,) = await load(
        db_engine, select(EvidenceItem).where(EvidenceItem.id == first.item_id)
    )
    assert item.sha256 == second_row.sha256
    assert item.captured_at == second.captured_at
    assert item.expires_at == second.captured_at + timedelta(days=365)
    assert ctx.files.count_client_files(client_id) == 2

    log = select(EvidenceLog).where(EvidenceLog.client_id == client_id)
    events = await load(db_engine, log.order_by(EvidenceLog.id))
    assert [event.event_type for event in events] == [
        "evidence.added",
        "evidence.revised",
    ]
    assert events[1].payload["revision"] == 2
    async with async_sessionmaker(db_engine)() as session:
        assert (await verify_chain(session, client_id)).ok
        (view,) = await list_evidence(session, client_id, NOW)
    assert (view.revisions, view.files_kept) == (2, 2)
    actions = [event.action for event in await audit_since(db_engine, baseline)]
    assert actions == ["evidence.revised"]


IMMUTABLE_CHANGES = [
    "sha256 = repeat('0', 64)",
    "size_bytes = 1",
    "note = 'changed'",
    "reviewer = 'Someone Else'",
    "reviewed_on = DATE '2020-01-01'",
    "revision_number = 9",
    "created_at = now()",
    "item_id = item_id + 1000",
    "id = id + 1000",
    "supersedes_id = id",
    "created_by_id = 1",
]


@pytest.mark.parametrize("change", IMMUTABLE_CHANGES)
async def test_the_database_rejects_a_change_to_a_recorded_revision(
    db_engine: AsyncEngine, ctx: EvidenceContext, change: str
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    stored = await upload(db_engine, ctx, client_id, manual(FIRST))
    with pytest.raises(DBAPIError, match="immutable"):
        async with db_engine.begin() as connection:
            await connection.execute(
                text(f"UPDATE evidence_revision SET {change} WHERE id = :id"),
                {"id": stored.revision_id},
            )
    (row,) = await revisions_of(db_engine, stored.item_id)
    assert row.sha256 == stored.sha256


async def test_only_the_file_reference_and_its_retention_date_can_change(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    first = await upload(db_engine, ctx, client_id, manual(FIRST))
    later = manual(SECOND, day=5)
    second = await revise(db_engine, ctx, client_id, first.item_id, later)
    async with db_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE evidence_revision SET storage_key = NULL, "
                "raw_expires_at = NULL WHERE id = :id"
            ),
            {"id": first.revision_id},
        )
        # The database itself clears these links when what they point to goes.
        await connection.execute(
            text("UPDATE evidence_revision SET supersedes_id = NULL WHERE id = :id"),
            {"id": second.revision_id},
        )
        await connection.execute(
            text("UPDATE evidence_revision SET created_by_id = NULL WHERE id = :id"),
            {"id": second.revision_id},
        )
    first_row, second_row = await revisions_of(db_engine, first.item_id)
    assert first_row.storage_key is None
    assert second_row.supersedes_id is None
    assert first_row.sha256 == first.sha256


async def test_an_attestation_can_be_revised_but_not_with_the_same_statement(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    first = await upload(db_engine, ctx, client_id, statement(1))
    with pytest.raises(DuplicateEvidenceError, match="already uploaded"):
        await revise(db_engine, ctx, client_id, first.item_id, statement(1))
    second = await revise(db_engine, ctx, client_id, first.item_id, statement(9))
    assert second.revision_number == 2
    assert second.raw_retained is False
    assert ctx.files.count_client_files(client_id) == 0


async def test_a_revision_may_not_repeat_a_file_the_client_already_has(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    first = await upload(db_engine, ctx, client_id, manual(FIRST))
    with pytest.raises(DuplicateEvidenceError, match="Nothing was stored"):
        await revise(db_engine, ctx, client_id, first.item_id, manual(FIRST, day=4))
    assert len(await revisions_of(db_engine, first.item_id)) == 1


async def test_an_automatic_export_cannot_be_revised(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    export = await upload(db_engine, ctx, client_id, export_evidence())
    corrected = export_evidence(b"other,file\n")
    with pytest.raises(EvidenceRejectedError, match="cannot be revised"):
        await revise(db_engine, ctx, client_id, export.item_id, corrected)


async def test_a_revision_keeps_the_assurance_level_of_its_item(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    first = await upload(db_engine, ctx, client_id, manual(FIRST))
    with pytest.raises(EvidenceRejectedError, match="keeps the assurance level"):
        await revise(db_engine, ctx, client_id, first.item_id, statement(3))


async def test_a_revision_is_checked_like_an_upload(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    first = await upload(db_engine, ctx, client_id, manual(FIRST))
    without_reviewer = replace(manual(SECOND), reviewer=None)
    with pytest.raises(EvidenceRejectedError, match="needs a reviewer"):
        await revise(db_engine, ctx, client_id, first.item_id, without_reviewer)


async def test_a_revision_needs_an_existing_item_of_the_same_client(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    owner = await create_test_client(db_engine, ctx, "Owner")
    other = await create_test_client(db_engine, ctx, "Other")
    first = await upload(db_engine, ctx, owner, manual(FIRST))
    with pytest.raises(ItemNotFoundError, match="no such evidence item"):
        await revise(db_engine, ctx, owner, first.item_id + 1000, manual(SECOND))
    with pytest.raises(ItemNotFoundError):
        await revise(db_engine, ctx, other, first.item_id, manual(SECOND))
    with pytest.raises(ClientNotFoundError):
        await revise(db_engine, ctx, 987_654_321, first.item_id, manual(SECOND))
