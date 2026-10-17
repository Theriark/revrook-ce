"""Review fixes of phase 3: tiny decimals, huge counts and a file time that
contradicts the expiry (synthetic data only)."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.assurance import Assurance
from app.evidence.errors import EvidenceRejectedError
from app.evidence.service import EvidenceContext, NewEvidence, list_evidence
from app.importers.base import ParsedFact, ParseResult
from app.importers.framework import (
    RowError,
    number_text,
    parse_number,
    read_count,
)
from app.models import EvidenceItem, EvidenceLog, Fact
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

TINY = "1e-999990"
UPLOADED_AT = NOW - timedelta(days=1)


class DatedImporter:
    """An importer that finds a capture time in the file, like the real ones."""

    version = "dated-1"

    def __init__(self, source_code: str, captured_at: datetime) -> None:
        self.source_code = source_code
        self.captured_at = captured_at

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        fact = ParsedFact(key="k", value={"count": 1})
        return ParseResult(facts=(fact,), captured_at=self.captured_at)


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    # Raw files are kept for a week, so a file left behind would be visible.
    return make_context(settings, tmp_path, raw_retention_days=7)


def export(source: str, data: bytes) -> NewEvidence:
    return NewEvidence(
        source_code=source,
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=UPLOADED_AT,
        data=data,
    )


def score_csv(*rows: str) -> bytes:
    return ("Date,Score\n" + "".join(f"{row}\n" for row in rows)).encode()


def score_json(**changes: Any) -> bytes:
    """A Secure Score answer; a value is written as given (a str is raw JSON)."""
    fields: dict[str, Any] = {
        "createdDateTime": '"2026-10-10T00:00:00Z"',
        "currentScore": "50",
        "maxScore": "100",
        **changes,
    }
    body = ", ".join(f"{json.dumps(name)}: {raw}" for name, raw in fields.items())
    return f"{{{body}}}".encode()


async def stored_facts(engine: AsyncEngine, item_id: int) -> list[Fact]:
    query = select(Fact).where(Fact.evidence_item_id == item_id).order_by(Fact.id)
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(query)).scalars())


async def item_count(engine: AsyncEngine, client_id: int) -> int:
    query = select(EvidenceItem).where(EvidenceItem.client_id == client_id)
    async with async_sessionmaker(engine)() as session:
        return len((await session.execute(query)).all())


async def chain_length(engine: AsyncEngine, client_id: int) -> int:
    query = select(EvidenceLog).where(EvidenceLog.client_id == client_id)
    async with async_sessionmaker(engine)() as session:
        return len((await session.execute(query)).all())


# --- B1: a tiny decimal ------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [TINY, "0.0000001", Decimal(TINY), Decimal("1E-7"), "1e-7", "12.1234567"],
)
def test_a_number_with_more_than_six_decimal_places_is_refused(value: object) -> None:
    with pytest.raises(ValueError, match="not a plausible number"):
        parse_number(value)


def test_a_number_with_up_to_six_decimal_places_is_still_read() -> None:
    assert parse_number("0.000001") == Decimal("0.000001")
    assert parse_number("48.123456") == Decimal("48.123456")
    # Trailing zeros are not places.
    assert parse_number("1.500000000") == Decimal("1.5")
    assert parse_number("1e-6") == Decimal("0.000001")
    # Zero is zero however it is written.
    assert parse_number("0e-999990") == 0
    assert parse_number("0.00000000000") == 0


def test_the_text_of_a_number_is_short_and_a_wild_number_raises() -> None:
    assert number_text(Decimal("0.000001")) == "0.000001"
    assert number_text(Decimal("123456789.123456")) == "123456789.123456"
    assert number_text(Decimal("1E+9")) == "1000000000"
    assert number_text(Decimal("0E-999990")) == "0"
    for wild in (Decimal(TINY), Decimal("1E+999990"), Decimal("NaN")):
        with pytest.raises(ValueError, match="not a plausible number"):
            number_text(wild)


async def test_a_tiny_secure_score_in_csv_rejects_its_row_and_nothing_else(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    data = score_csv(f"2026-10-10T00:00:00Z,{TINY}", "2026-10-09T00:00:00Z,50")
    stored = await upload(db_engine, ctx, client_id, export("secure-score", data))
    facts = await stored_facts(db_engine, stored.item_id)
    (summary,) = [fact for fact in facts if fact.fact_key.endswith(".summary")]
    assert summary.value["rows_rejected"] == 1
    assert summary.value["current_score"] == "50"
    (reject,) = [fact for fact in facts if fact.fact_key.endswith(".reject")]
    assert reject.value == {"row": 1, "reason": "Score must be a number"}
    assert max(len(json.dumps(fact.value)) for fact in facts) < 1000


async def test_a_file_with_only_a_tiny_score_in_csv_is_refused_not_a_500(
    db_engine: AsyncEngine, ctx: EvidenceContext, tmp_path: Path
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    data = score_csv(f"2026-10-10T00:00:00Z,{TINY}")
    with pytest.raises(EvidenceRejectedError, match="No row of the file could be read"):
        await upload(db_engine, ctx, client_id, export("secure-score", data))
    assert await item_count(db_engine, client_id) == 0
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


async def test_a_tiny_secure_score_in_json_is_refused_not_a_500(
    db_engine: AsyncEngine, ctx: EvidenceContext, tmp_path: Path
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    data = score_json(currentScore=TINY)
    with pytest.raises(EvidenceRejectedError, match="Score must be a number"):
        await upload(db_engine, ctx, client_id, export("secure-score", data))
    maximum = score_json(maxScore=TINY)
    with pytest.raises(EvidenceRejectedError, match="Max score must be a number"):
        await upload(db_engine, ctx, client_id, export("secure-score", maximum))
    assert await item_count(db_engine, client_id) == 0
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


async def test_a_tiny_control_score_in_json_rejects_that_control_only(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    controls = (
        '[{"controlName": "Admin MFA", "score": ' + TINY + "},"
        ' {"controlName": "Block legacy", "score": 3.5}]'
    )
    data = score_json(controlScores=controls)
    stored = await upload(db_engine, ctx, client_id, export("secure-score", data))
    facts = await stored_facts(db_engine, stored.item_id)
    (control,) = [fact for fact in facts if fact.fact_key.endswith(".control")]
    assert control.value["score"] == "3.5"
    (reject,) = [fact for fact in facts if fact.fact_key.endswith(".reject")]
    assert "score of a controlScores entry must be a number" in reject.value["reason"]


# --- N1: a count with too many digits ---------------------------------------


@pytest.mark.parametrize("count", ["9" * 19, "1" * 5000, "0" * 19, 10**18])
def test_a_count_with_more_than_eighteen_digits_is_a_row_error(count: object) -> None:
    with pytest.raises(RowError, match="Count must be a whole number"):
        read_count({"c": count}, "c", "Count")


def test_a_count_of_up_to_eighteen_digits_is_read() -> None:
    assert read_count({"c": "9" * 18}, "c", "Count") == 10**18 - 1
    assert read_count({"c": 10**18 - 1}, "c", "Count") == 10**18 - 1
    assert read_count({"c": " 0042 "}, "c", "Count") == 42


async def test_a_huge_user_count_in_json_is_a_row_reject_not_a_500(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    data = score_json(licensedUserCount='"' + "1" * 5000 + '"')
    with pytest.raises(EvidenceRejectedError, match="licensedUserCount must be a whole"):
        await upload(db_engine, ctx, client_id, export("secure-score", data))
    assert await item_count(db_engine, client_id) == 0


# --- B2: the expiry against the capture time found in the file --------------


async def test_an_expiry_before_the_capture_time_in_the_file_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext, tmp_path: Path
) -> None:
    file_time = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    ctx.importers.register(DatedImporter("dated-source", file_time))
    client_id = await create_test_client(db_engine, ctx)
    baseline = await audit_baseline(db_engine)
    evidence = replace(
        export_evidence(b"x", datetime(2026, 10, 1, 9, 0, tzinfo=UTC)),
        source_code="dated-source",
        expires_at=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
    )
    with pytest.raises(EvidenceRejectedError, match="after the capture time found"):
        await upload(db_engine, ctx, client_id, evidence)

    assert await item_count(db_engine, client_id) == 0
    assert await chain_length(db_engine, client_id) == 0
    assert await audit_since(db_engine, baseline) == []
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
    assert ctx.files.count_client_files(client_id) == 0
    # The client's evidence list still works, and shows nothing.
    async with async_sessionmaker(db_engine)() as session:
        assert await list_evidence(session, client_id, NOW) == []

    # The same upload with an expiry after the file time is accepted.
    fine = replace(evidence, expires_at=file_time + timedelta(days=1))
    stored = await upload(db_engine, ctx, client_id, fine)
    assert stored.captured_at == file_time
    assert stored.expires_at == file_time + timedelta(days=1)
    async with async_sessionmaker(db_engine)() as session:
        views = await list_evidence(session, client_id, NOW)
    assert [view.item_id for view in views] == [stored.item_id]


async def test_an_expiry_equal_to_the_capture_time_in_the_file_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    file_time = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    ctx.importers.register(DatedImporter("dated-source", file_time))
    client_id = await create_test_client(db_engine, ctx)
    evidence = replace(
        export_evidence(b"x", datetime(2026, 10, 1, 9, 0, tzinfo=UTC)),
        source_code="dated-source",
        expires_at=file_time,
    )
    with pytest.raises(EvidenceRejectedError, match="after the capture time found"):
        await upload(db_engine, ctx, client_id, evidence)
    assert await item_count(db_engine, client_id) == 0
