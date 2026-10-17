"""Phase 2 carry-over: implausible times are refused, no raw file is left behind."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence import service
from app.evidence.assurance import Assurance
from app.evidence.errors import EvidenceRejectedError
from app.evidence.service import EvidenceContext, NewEvidence, add_revision
from app.importers.base import ParsedFact, ParseResult
from app.settings import Settings
from helpers import (
    NOW,
    create_test_client,
    export_evidence,
    make_context,
    scalar,
    upload,
)


class DatedImporter:
    """A source whose file says when it was captured."""

    source_code = "dated-source"
    version = "dated-1"

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        fact = ParsedFact("dated.summary", {"rows": 1})
        return ParseResult(facts=(fact,), captured_at=self.moment)


def dated() -> NewEvidence:
    return NewEvidence(
        source_code="dated-source",
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=NOW - timedelta(days=2),
        data=b"synthetic",
    )


def manual(data: bytes) -> NewEvidence:
    return NewEvidence(
        source_code="restore-test",
        assurance=Assurance.MANUAL_ARTEFACT,
        captured_at=NOW - timedelta(days=5),
        data=data,
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, 1),
        note="Restore test",
    )


async def chain_down(*args: object, **kwargs: object) -> None:
    raise RuntimeError("the chain could not be written")


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(settings, tmp_path, raw_retention_days=7)


async def test_a_capture_time_before_the_year_2000_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    old = replace(export_evidence(), captured_at=datetime(1999, 12, 31, tzinfo=UTC))
    with pytest.raises(EvidenceRejectedError, match="before the year 2000"):
        await upload(db_engine, ctx, client_id, old)
    assert ctx.files.count_client_files(client_id) == 0
    assert await scalar(db_engine, "SELECT count(*) FROM evidence_item") == 0


async def test_an_expiry_after_the_year_2199_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    far = replace(export_evidence(), expires_at=datetime(2200, 1, 2, tzinfo=UTC))
    with pytest.raises(EvidenceRejectedError, match="after the year 2199"):
        await upload(db_engine, ctx, client_id, far)
    near = replace(export_evidence(), expires_at=datetime(2199, 12, 31, tzinfo=UTC))
    stored = await upload(db_engine, ctx, client_id, near)
    assert stored.expires_at == datetime(2199, 12, 31, tzinfo=UTC)


@pytest.mark.parametrize(
    ("moment", "message"),
    [
        (datetime(1999, 12, 31, tzinfo=UTC), "found in the file is before the year"),
        (NOW + timedelta(days=1), "found in the file is in the future"),
        (datetime(2026, 10, 1), "found in the file must include a time zone"),
    ],
)
async def test_an_implausible_capture_time_found_in_a_file_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext, moment: datetime, message: str
) -> None:
    ctx.importers.register(DatedImporter(moment))
    client_id = await create_test_client(db_engine, ctx)
    with pytest.raises(EvidenceRejectedError, match=message):
        await upload(db_engine, ctx, client_id, dated())
    assert ctx.files.count_client_files(client_id) == 0


async def test_a_plausible_capture_time_found_in_a_file_is_used(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    moment = NOW - timedelta(days=9)
    ctx.importers.register(DatedImporter(moment))
    client_id = await create_test_client(db_engine, ctx)
    stored = await upload(db_engine, ctx, client_id, dated())
    assert stored.captured_at == moment
    assert stored.raw_retained is True
    assert ctx.files.count_client_files(client_id) == 1


@pytest.mark.parametrize("kind", ["export", "manual"])
async def test_no_file_is_left_when_the_chain_record_cannot_be_written(
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    evidence = export_evidence() if kind == "export" else manual(b"%PDF-1.4 first")
    monkeypatch.setattr(service, "append_record", chain_down)
    with pytest.raises(RuntimeError, match="chain could not be written"):
        await upload(db_engine, ctx, client_id, evidence)
    assert ctx.files.count_client_files(client_id) == 0
    assert await scalar(db_engine, "SELECT count(*) FROM evidence_item") == 0
    assert await scalar(db_engine, "SELECT count(*) FROM evidence_revision") == 0


async def test_no_file_is_left_when_a_revision_cannot_be_chained(
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    first = await upload(db_engine, ctx, client_id, manual(b"%PDF-1.4 first"))
    assert ctx.files.count_client_files(client_id) == 1
    monkeypatch.setattr(service, "append_record", chain_down)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    with pytest.raises(RuntimeError, match="chain could not be written"):
        async with factory() as session, session.begin():
            await add_revision(
                session,
                ctx,
                client_id,
                first.item_id,
                manual(b"%PDF-1.4 second"),
                NOW,
            )
    assert ctx.files.count_client_files(client_id) == 1
    assert await scalar(db_engine, "SELECT count(*) FROM evidence_revision") == 1
