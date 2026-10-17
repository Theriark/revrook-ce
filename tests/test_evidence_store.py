"""Uploading evidence: duplicates, pseudonyms, raw retention and refusals."""

import asyncio
import hashlib
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.clients import pseudonym_key
from app.evidence import retention
from app.evidence.assurance import Assurance
from app.evidence.chain import verify_chain
from app.evidence.errors import (
    ClientNotFoundError,
    DuplicateEvidenceError,
    EvidenceRejectedError,
    EvidenceTooLargeError,
    PersonalIdentifierError,
)
from app.evidence.expiry import Freshness
from app.evidence.retention import purge_expired_raw
from app.evidence.service import EvidenceContext, NewEvidence, list_evidence
from app.importers.base import ParsedFact, ParseResult
from app.models import Client, EvidenceItem, EvidenceLog, EvidenceRevision, Fact
from app.pseudonym import pseudonymise
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
    upload,
    users_csv,
)

REVIEWED = date(2026, 10, 1)


def manual_evidence(data: bytes = b"%PDF-1.4 synthetic restore test") -> NewEvidence:
    return NewEvidence(
        source_code="restore-test",
        assurance=Assurance.MANUAL_ARTEFACT,
        captured_at=NOW - timedelta(days=10),
        data=data,
        reviewer="Sam Reviewer",
        reviewed_on=REVIEWED,
        note="Restore test of the file server",
    )


def attestation(note: str = "Staff training was completed in Q3") -> NewEvidence:
    return NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=NOW - timedelta(days=3),
        reviewer="Sam Reviewer",
        reviewed_on=REVIEWED,
        note=note,
    )


class FakeImporter:
    """An importer that returns a prepared result, for the edge cases."""

    version = "fake-1"

    def __init__(self, source_code: str, result: ParseResult) -> None:
        self.source_code = source_code
        self.result = result

    def parse(self, data: bytes, max_rows: int) -> ParseResult:
        return self.result


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(settings, tmp_path)


async def rows(engine: AsyncEngine, statement: Select[Any]) -> list[Any]:
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(statement)).scalars())


async def facts_of(engine: AsyncEngine, item_id: int) -> list[Fact]:
    query = select(Fact).where(Fact.evidence_item_id == item_id).order_by(Fact.id)
    return await rows(engine, query)


async def revisions_of(engine: AsyncEngine, item_id: int) -> list[EvidenceRevision]:
    query = select(EvidenceRevision).where(EvidenceRevision.item_id == item_id)
    return await rows(engine, query.order_by(EvidenceRevision.revision_number))


async def item_count(engine: AsyncEngine, client_id: int) -> int:
    query = select(EvidenceItem).where(EvidenceItem.client_id == client_id)
    return len(await rows(engine, query))


async def chain_events(engine: AsyncEngine, client_id: int) -> list[EvidenceLog]:
    query = select(EvidenceLog).where(EvidenceLog.client_id == client_id)
    return await rows(engine, query.order_by(EvidenceLog.id))


async def client_key(
    engine: AsyncEngine, ctx: EvidenceContext, client_id: int
) -> bytes:
    async with async_sessionmaker(engine)() as session:
        client = await session.get(Client, client_id)
    assert client is not None
    return pseudonym_key(ctx.cipher, client)


async def test_an_export_is_stored_as_facts_with_pseudonyms_and_a_chain_record(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    baseline = await audit_baseline(db_engine)
    data = users_csv()
    stored = await upload(db_engine, ctx, client_id, export_evidence(data))

    assert stored.revision_number == 1
    assert stored.facts == len(SYNTHETIC_USERS) + 1
    assert stored.sha256 == hashlib.sha256(data).hexdigest()
    assert stored.size_bytes == len(data)
    assert stored.assurance is Assurance.AUTOMATIC_EXPORT
    assert stored.expires_at == stored.captured_at + timedelta(days=35)
    assert stored.raw_retained is False

    key = await client_key(db_engine, ctx, client_id)
    facts = await facts_of(db_engine, stored.item_id)
    users = [fact for fact in facts if fact.fact_key == "reference.user"]
    assert [fact.value["user"] for fact in users] == [
        pseudonymise(key, upn) for upn, _ in SYNTHETIC_USERS
    ]
    assert all(re.fullmatch(r"[0-9a-f]{16}", fact.value["user"]) for fact in users)
    assert [fact.value["mfa_registered"] for fact in users] == [
        flag for _, flag in SYNTHETIC_USERS
    ]
    summary = next(fact for fact in facts if fact.fact_key == "reference.summary")
    assert summary.value == {"users": 3, "mfa_registered": 2}
    assert all(fact.captured_at == stored.captured_at for fact in facts)

    (record,) = await chain_events(db_engine, client_id)
    assert record.event_type == "evidence.added"
    assert record.evidence_item_id == stored.item_id
    assert record.payload["sha256"] == stored.sha256
    assert record.payload["facts"] == 4
    assert record.payload["raw_retained"] is False
    async with async_sessionmaker(db_engine)() as session:
        assert (await verify_chain(session, client_id)).ok

    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["evidence.added"]
    assert events[0].detail == {
        "client_id": client_id,
        "source_code": "reference-csv",
        "assurance": "automatic-export",
    }


async def test_no_synthetic_user_name_survives_anywhere_in_the_database(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    await upload(db_engine, ctx, client_id, export_evidence())
    dump = (await database_dump(db_engine)).lower()
    assert "fact" in dump and "reference.summary" in dump
    for upn, _ in SYNTHETIC_USERS:
        assert upn not in dump
        assert upn.split("@", maxsplit=1)[0] not in dump


async def test_pseudonyms_are_stable_within_a_client_and_differ_between_clients(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    first = await create_test_client(db_engine, ctx, "First Client")
    second = await create_test_client(db_engine, ctx, "Second Client")
    alice = ("alice.synthetic@example.test", True)
    carol = ("carol.synthetic@example.test", True)
    only_alice = export_evidence(users_csv((alice,)))
    carol_and_alice = export_evidence(users_csv((carol, alice)))
    one = await upload(db_engine, ctx, first, only_alice)
    two = await upload(db_engine, ctx, first, carol_and_alice)
    other = await upload(db_engine, ctx, second, only_alice)

    async def users(item_id: int) -> list[str]:
        found = await facts_of(db_engine, item_id)
        return [f.value["user"] for f in found if f.fact_key == "reference.user"]

    (alice_in_one,) = await users(one.item_id)
    carol_in_two, alice_in_two = await users(two.item_id)
    (alice_elsewhere,) = await users(other.item_id)
    assert alice_in_one == alice_in_two
    assert alice_in_one != carol_in_two
    assert alice_elsewhere != alice_in_one


async def test_a_duplicate_upload_for_the_same_client_is_refused_readably(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    other_client = await create_test_client(db_engine, ctx, "Other Client")
    first = await upload(db_engine, ctx, client_id, export_evidence())
    baseline = await audit_baseline(db_engine)

    with pytest.raises(DuplicateEvidenceError) as refused:
        await upload(
            db_engine,
            ctx,
            client_id,
            export_evidence(captured_at=NOW - timedelta(days=1)),
        )
    message = str(refused.value)
    assert "already uploaded for this client on 2026-10-17" in message
    assert f"evidence item {first.item_id}" in message
    assert "Nothing was stored" in message
    assert refused.value.existing_item_id == first.item_id

    assert await item_count(db_engine, client_id) == 1
    assert len(await facts_of(db_engine, first.item_id)) == 4
    assert len(await chain_events(db_engine, client_id)) == 1
    assert await audit_since(db_engine, baseline) == []
    # Another client may hold the same file.
    await upload(db_engine, ctx, other_client, export_evidence())


async def test_with_no_raw_retention_no_file_is_ever_written(
    db_engine: AsyncEngine, ctx: EvidenceContext, tmp_path: Path
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    stored = await upload(db_engine, ctx, client_id, export_evidence())
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
    assert ctx.files.count_client_files(client_id) == 0
    (revision,) = await revisions_of(db_engine, stored.item_id)
    assert revision.storage_key is None
    assert revision.raw_expires_at is None
    assert revision.sha256 == stored.sha256


async def purge(db_engine: AsyncEngine, ctx: EvidenceContext, when: datetime) -> int:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        return await purge_expired_raw(session, ctx.files, when)


async def test_a_kept_raw_file_is_purged_exactly_when_its_retention_ends(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path, raw_retention_days=7)
    client_id = await create_test_client(db_engine, ctx)
    baseline = await audit_baseline(db_engine)
    data = users_csv()
    stored = await upload(db_engine, ctx, client_id, export_evidence(data))
    assert stored.raw_retained is True
    assert ctx.files.count_client_files(client_id) == 1
    (revision,) = await revisions_of(db_engine, stored.item_id)
    assert revision.storage_key is not None
    assert ctx.files.read(revision.storage_key) == data
    assert revision.raw_expires_at == NOW + timedelta(days=7)

    one_second_early = NOW + timedelta(days=7) - timedelta(seconds=1)
    assert await purge(db_engine, ctx, one_second_early) == 0
    assert ctx.files.count_client_files(client_id) == 1

    assert await purge(db_engine, ctx, NOW + timedelta(days=7)) == 1
    assert ctx.files.count_client_files(client_id) == 0
    assert await purge(db_engine, ctx, NOW + timedelta(days=30)) == 0
    (after,) = await revisions_of(db_engine, stored.item_id)
    assert after.storage_key is None
    assert after.sha256 == stored.sha256
    events = await chain_events(db_engine, client_id)
    assert [event.event_type for event in events] == [
        "evidence.added",
        "evidence.raw_purged",
    ]
    assert events[1].payload["sha256"] == stored.sha256
    async with async_sessionmaker(db_engine)() as session:
        assert (await verify_chain(session, client_id)).ok
    actions = [event.action for event in await audit_since(db_engine, baseline)]
    assert actions == ["evidence.added", "evidence.raw_purged"]


async def test_a_purge_leaves_the_file_of_a_client_that_vanished_meanwhile(
    db_engine: AsyncEngine,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_context(settings, tmp_path, raw_retention_days=1)
    client_id = await create_test_client(db_engine, ctx)
    await upload(db_engine, ctx, client_id, export_evidence())

    async def vanished(session: AsyncSession, client_id: int) -> Client:
        raise ClientNotFoundError("gone")

    monkeypatch.setattr(retention, "lock_client", vanished)
    assert await purge(db_engine, ctx, NOW + timedelta(days=2)) == 0
    assert ctx.files.count_client_files(client_id) == 1


async def test_a_manual_artefact_is_kept_with_its_reviewer_and_review_date(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    stored = await upload(db_engine, ctx, client_id, manual_evidence())
    assert stored.assurance is Assurance.MANUAL_ARTEFACT
    assert stored.raw_retained is True
    assert stored.facts == 0
    assert stored.expires_at == stored.captured_at + timedelta(days=365)
    (revision,) = await revisions_of(db_engine, stored.item_id)
    assert (revision.reviewer, revision.reviewed_on) == ("Sam Reviewer", REVIEWED)
    assert revision.note == "Restore test of the file server"
    assert revision.raw_expires_at is None
    assert revision.storage_key is not None
    assert ctx.files.read(revision.storage_key) == b"%PDF-1.4 synthetic restore test"
    # Retention applies to raw exports, never to an artefact kept as evidence.
    assert await purge(db_engine, ctx, NOW + timedelta(days=4000)) == 0
    assert ctx.files.count_client_files(client_id) == 1


async def test_an_attestation_has_no_file_and_an_explicit_expiry_wins(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    expires = NOW + timedelta(days=100)
    stored = await upload(
        db_engine, ctx, client_id, replace(attestation(), expires_at=expires)
    )
    assert stored.assurance is Assurance.ATTESTATION
    assert stored.raw_retained is False
    assert stored.size_bytes > 0
    assert stored.expires_at == expires
    assert ctx.files.count_client_files(client_id) == 0


async def test_the_same_attestation_on_another_day_is_new_evidence(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    await upload(db_engine, ctx, client_id, attestation())
    with pytest.raises(DuplicateEvidenceError, match="already uploaded"):
        await upload(db_engine, ctx, client_id, attestation())
    later = replace(attestation(), reviewed_on=date(2026, 10, 15))
    await upload(db_engine, ctx, client_id, later)
    assert await item_count(db_engine, client_id) == 2


INVALID_UPLOADS = [
    ("no reviewer", replace(manual_evidence(), reviewer=None), "needs a reviewer"),
    ("blank reviewer", replace(manual_evidence(), reviewer="  "), "needs a reviewer"),
    ("no date", replace(manual_evidence(), reviewed_on=None), "needs a reviewer"),
    (
        "attestation with a file",
        replace(attestation(), data=b"x"),
        "An attestation has no file",
    ),
    ("attestation without a note", replace(attestation(), note=None), "and a note"),
    ("empty file", export_evidence(b""), "missing or empty"),
    ("no file", replace(export_evidence(), data=None), "missing or empty"),
    (
        "bad source code",
        replace(export_evidence(), source_code="Bad Source"),
        "source code must be",
    ),
    (
        "no time zone",
        replace(export_evidence(), captured_at=datetime(2026, 10, 1, 9, 0)),
        "capture time must include a time zone",
    ),
    (
        "capture in the future",
        replace(export_evidence(), captured_at=NOW + timedelta(days=1)),
        "capture time is in the future",
    ),
    (
        "expiry before capture",
        replace(manual_evidence(), expires_at=NOW - timedelta(days=11)),
        "expiry must be after",
    ),
    (
        "expiry without a time zone",
        replace(manual_evidence(), expires_at=datetime(2027, 1, 1)),
        "expiry time must include a time zone",
    ),
    (
        "reviewer too long",
        replace(manual_evidence(), reviewer="r" * 101),
        "at most 100 characters",
    ),
    (
        "note too long",
        replace(manual_evidence(), note="n" * 2001),
        "at most 2000 characters",
    ),
    (
        "NUL in the reviewer",
        replace(manual_evidence(), reviewer="Sam\x00Reviewer"),
        "reviewer must not contain a NUL",
    ),
    (
        "NUL in the note",
        replace(attestation(), note="a\x00b"),
        "note must not contain a NUL",
    ),
    (
        "review date in the future",
        replace(manual_evidence(), reviewed_on=date(2026, 12, 1)),
        "review date is in the future",
    ),
    (
        "no importer",
        replace(export_evidence(), source_code="unknown-source"),
        "no importer for the source unknown-source",
    ),
    (
        "wrong columns",
        export_evidence(b"name,flag\nx,y\n"),
        "missing the column user_principal_name, mfa_registered",
    ),
]


@pytest.mark.parametrize(
    ("evidence", "message"),
    [pytest.param(e, m, id=name) for name, e, m in INVALID_UPLOADS],
)
async def test_an_invalid_upload_is_refused_and_nothing_is_stored(
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    tmp_path: Path,
    evidence: NewEvidence,
    message: str,
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    baseline = await audit_baseline(db_engine)
    with pytest.raises(EvidenceRejectedError, match=message):
        await upload(db_engine, ctx, client_id, evidence)
    assert await item_count(db_engine, client_id) == 0
    assert await chain_events(db_engine, client_id) == []
    assert await audit_since(db_engine, baseline) == []
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


async def test_a_file_over_the_size_limit_is_refused(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path, import_max_bytes=10)
    client_id = await create_test_client(db_engine, ctx)
    with pytest.raises(EvidenceTooLargeError, match="larger than the limit"):
        await upload(db_engine, ctx, client_id, manual_evidence(b"x" * 11))
    await upload(db_engine, ctx, client_id, manual_evidence(b"x" * 10))
    assert await item_count(db_engine, client_id) == 1


async def test_a_file_with_more_rows_than_the_limit_is_refused(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path, import_max_rows=2)
    client_id = await create_test_client(db_engine, ctx)
    with pytest.raises(EvidenceRejectedError, match="more than 2 rows"):
        await upload(db_engine, ctx, client_id, export_evidence())
    assert await item_count(db_engine, client_id) == 0


async def test_an_unknown_client_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    with pytest.raises(ClientNotFoundError, match="no client with this id"):
        await upload(db_engine, ctx, 987_654_321, export_evidence())


async def test_a_value_that_looks_like_an_email_address_stops_the_upload(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    leaky = ParsedFact(key="leak", value={"contact": "someone@example.test"})
    ctx.importers.register(FakeImporter("leaky-source", ParseResult(facts=(leaky,))))
    client_id = await create_test_client(db_engine, ctx)
    evidence = replace(export_evidence(b"x"), source_code="leaky-source")
    with pytest.raises(PersonalIdentifierError, match="looks like an email address"):
        await upload(db_engine, ctx, client_id, evidence)
    assert await item_count(db_engine, client_id) == 0
    assert "someone@example.test" not in await database_dump(db_engine)


async def test_a_field_given_as_value_and_identifier_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    twice = ParsedFact(key="k", value={"user": "x"}, identifiers={"user": "y"})
    ctx.importers.register(FakeImporter("twice-source", ParseResult(facts=(twice,))))
    client_id = await create_test_client(db_engine, ctx)
    evidence = replace(export_evidence(b"x"), source_code="twice-source")
    with pytest.raises(EvidenceRejectedError, match="field user of k twice"):
        await upload(db_engine, ctx, client_id, evidence)


async def test_an_empty_identifier_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    blank = ParsedFact(key="k", value={}, identifiers={"user": "   "})
    ctx.importers.register(FakeImporter("blank-source", ParseResult(facts=(blank,))))
    client_id = await create_test_client(db_engine, ctx)
    evidence = replace(export_evidence(b"x"), source_code="blank-source")
    with pytest.raises(EvidenceRejectedError, match="field user of k is empty"):
        await upload(db_engine, ctx, client_id, evidence)


async def test_a_capture_time_found_in_the_file_wins_over_the_form(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    fact = ParsedFact(key="k", value={"count": 3, "flag": True, "none": None})
    from_file = NOW - timedelta(days=5)
    result = ParseResult(facts=(fact,), captured_at=from_file)
    ctx.importers.register(FakeImporter("dated-source", result))
    client_id = await create_test_client(db_engine, ctx)
    evidence = replace(export_evidence(b"x"), source_code="dated-source")
    stored = await upload(db_engine, ctx, client_id, evidence)
    assert stored.captured_at == from_file
    assert stored.expires_at == from_file + timedelta(days=35)
    (only,) = await facts_of(db_engine, stored.item_id)
    assert only.captured_at == from_file
    assert only.value == {"count": 3, "flag": True, "none": None}


async def test_two_uploads_at_once_for_one_client_both_land_in_one_chain(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    one = export_evidence(users_csv((SYNTHETIC_USERS[0],)))
    two = export_evidence(users_csv((SYNTHETIC_USERS[1],)))
    results = await asyncio.gather(
        upload(db_engine, ctx, client_id, one), upload(db_engine, ctx, client_id, two)
    )
    assert len({stored.item_id for stored in results}) == 2
    events = await chain_events(db_engine, client_id)
    assert len(events) == 2
    assert events[1].previous_hash == events[0].record_hash
    async with async_sessionmaker(db_engine)() as session:
        assert (await verify_chain(session, client_id)).ok


async def test_the_same_file_uploaded_twice_at_once_is_stored_once(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    outcomes = await asyncio.gather(
        upload(db_engine, ctx, client_id, export_evidence()),
        upload(db_engine, ctx, client_id, export_evidence()),
        return_exceptions=True,
    )
    refused = [o for o in outcomes if isinstance(o, DuplicateEvidenceError)]
    assert len(refused) == 1
    assert await item_count(db_engine, client_id) == 1
    assert len(await chain_events(db_engine, client_id)) == 1


async def test_the_list_shows_freshness_at_the_time_asked(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    captured = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    old = await upload(
        db_engine, ctx, client_id, export_evidence(captured_at=captured), captured
    )
    newer = await upload(
        db_engine,
        ctx,
        client_id,
        manual_evidence(),
        captured + timedelta(days=50),
    )

    async def freshness(as_of: datetime) -> dict[int, Freshness]:
        async with async_sessionmaker(db_engine)() as session:
            views = await list_evidence(session, client_id, as_of)
        return {view.item_id: view.freshness for view in views}

    expires = old.expires_at
    at_limit = await freshness(expires)
    just_after = await freshness(expires + timedelta(seconds=1))
    at_twice = await freshness(expires + timedelta(days=35))
    assert at_limit[old.item_id] is Freshness.CURRENT
    assert just_after[old.item_id] is Freshness.STALE
    assert at_twice[old.item_id] is Freshness.EXPIRED
    assert at_limit[newer.item_id] is Freshness.CURRENT

    async with async_sessionmaker(db_engine)() as session:
        views = await list_evidence(session, client_id, expires)
    # Newest capture first: the manual artefact was captured after the export.
    assert [view.item_id for view in views] == [newer.item_id, old.item_id]
    manual, export = views
    assert manual.assurance is Assurance.MANUAL_ARTEFACT
    assert (manual.revisions, manual.files_kept) == (1, 1)
    assert (export.revisions, export.files_kept) == (1, 0)


async def test_listing_an_unknown_client_is_refused(db_engine: AsyncEngine) -> None:
    async with async_sessionmaker(db_engine)() as session:
        with pytest.raises(ClientNotFoundError):
            await list_evidence(session, 987_654_321, NOW)
