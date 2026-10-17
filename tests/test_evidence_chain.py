"""The evidence hash chain: linking, verification and tamper detection."""

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence import chain
from app.evidence.chain import (
    CONTENT_MISMATCH,
    GENESIS_HASH,
    PREVIOUS_MISMATCH,
    ChainResult,
    append_record,
    canonical_json,
    chained_client_ids,
    compute_record_hash,
    head_hash,
    iso_utc,
    verify_all,
    verify_chain,
)
from app.evidence.locking import lock_client
from app.models import EvidenceLog
from app.settings import Settings
from helpers import NOW, change_log, create_test_client, log_unprotected, make_context


async def append(engine: AsyncEngine, client_id: int, number: int) -> EvidenceLog:
    """Append one record in its own transaction, as the evidence service does."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await lock_client(session, client_id)
        return await append_record(
            session,
            client_id=client_id,
            event_type="test.step",
            payload={"n": number, "note": "synthetic"},
            now=NOW + timedelta(seconds=number),
        )


async def build_chain(
    engine: AsyncEngine, client_id: int, length: int
) -> list[EvidenceLog]:
    return [await append(engine, client_id, number) for number in range(length)]


async def verify(engine: AsyncEngine, client_id: int) -> ChainResult:
    async with async_sessionmaker(engine)() as session:
        return await verify_chain(session, client_id)


async def new_client(engine: AsyncEngine, settings: Settings, tmp_path: Path) -> int:
    return await create_test_client(engine, make_context(settings, tmp_path))


async def test_records_link_to_the_one_before_and_the_chain_verifies(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    client_id = await new_client(db_engine, settings, tmp_path)
    first, second, third = await build_chain(db_engine, client_id, 3)
    assert first.previous_hash == GENESIS_HASH
    assert second.previous_hash == first.record_hash
    assert third.previous_hash == second.record_hash
    assert len({first.record_hash, second.record_hash, third.record_hash}) == 3
    assert all(re.fullmatch(r"[0-9a-f]{64}", r.record_hash) for r in (first, second))

    result = await verify(db_engine, client_id)
    assert result == ChainResult(
        client_id=client_id,
        ok=True,
        records=3,
        head_hash=third.record_hash,
    )
    async with async_sessionmaker(db_engine)() as session:
        assert await head_hash(session, client_id) == third.record_hash


async def test_an_empty_chain_verifies_and_its_head_is_the_genesis_hash(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    client_id = await new_client(db_engine, settings, tmp_path)
    result = await verify(db_engine, client_id)
    assert (result.ok, result.records, result.head_hash) == (True, 0, GENESIS_HASH)


async def test_a_changed_middle_record_is_detected_at_that_record(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    client_id = await new_client(db_engine, settings, tmp_path)
    records = await build_chain(db_engine, client_id, 5)
    middle = records[2]
    async with log_unprotected(db_engine, client_id):
        await change_log(
            db_engine,
            "UPDATE evidence_log SET payload = CAST(:payload AS jsonb) WHERE id = :id",
            payload='{"n": 99, "note": "changed"}',
            id=middle.id,
        )
        result = await verify(db_engine, client_id)
    assert result.ok is False
    assert result.failed_record_id == middle.id
    assert result.reason == CONTENT_MISMATCH
    assert result.records == 3
    assert (await verify(db_engine, client_id)).ok is True


async def test_a_rewritten_record_with_a_fixed_hash_breaks_the_next_record(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    client_id = await new_client(db_engine, settings, tmp_path)
    records = await build_chain(db_engine, client_id, 4)
    target, following = records[1], records[2]
    forged_payload = {"n": 99, "note": "forged"}
    forged_hash = compute_record_hash(
        client_id=client_id,
        evidence_item_id=None,
        event_type=target.event_type,
        payload=forged_payload,
        previous_hash=target.previous_hash,
        created_at=target.created_at,
    )
    async with log_unprotected(db_engine, client_id):
        await change_log(
            db_engine,
            "UPDATE evidence_log SET payload = CAST(:payload AS jsonb), "
            "record_hash = :hash WHERE id = :id",
            payload='{"n": 99, "note": "forged"}',
            hash=forged_hash,
            id=target.id,
        )
        result = await verify(db_engine, client_id)
    assert result.ok is False
    assert result.failed_record_id == following.id
    assert result.reason == PREVIOUS_MISMATCH


async def test_a_removed_middle_record_is_detected_at_the_record_after_it(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    client_id = await new_client(db_engine, settings, tmp_path)
    records = await build_chain(db_engine, client_id, 4)
    async with log_unprotected(db_engine, client_id):
        await change_log(
            db_engine, "DELETE FROM evidence_log WHERE id = :id", id=records[1].id
        )
        result = await verify(db_engine, client_id)
    assert result.ok is False
    assert result.failed_record_id == records[2].id
    assert result.reason == PREVIOUS_MISMATCH
    assert (await verify(db_engine, client_id)).records == 4


async def test_a_changed_link_is_detected_at_the_record_that_holds_it(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    client_id = await new_client(db_engine, settings, tmp_path)
    records = await build_chain(db_engine, client_id, 3)
    async with log_unprotected(db_engine, client_id):
        await change_log(
            db_engine,
            "UPDATE evidence_log SET previous_hash = :zeros WHERE id = :id",
            zeros="1" * 64,
            id=records[1].id,
        )
        result = await verify(db_engine, client_id)
    assert (result.ok, result.failed_record_id) == (False, records[1].id)
    assert result.reason == PREVIOUS_MISMATCH


async def test_chains_are_separate_for_each_client(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    first = await new_client(db_engine, settings, tmp_path)
    second = await new_client(db_engine, settings, tmp_path)
    first_records = await build_chain(db_engine, first, 3)
    await build_chain(db_engine, second, 2)
    assert first_records[0].previous_hash == GENESIS_HASH
    async with log_unprotected(db_engine, first):
        await change_log(
            db_engine,
            "UPDATE evidence_log SET event_type = 'test.changed' WHERE id = :id",
            id=first_records[0].id,
        )
        async with async_sessionmaker(db_engine)() as session:
            ids = await chained_client_ids(session)
            results = {r.client_id: r for r in await verify_all(session)}
    assert first in ids and second in ids
    assert results[first].ok is False
    assert results[second].ok is True
    assert results[second].records == 2


async def test_a_long_chain_is_checked_in_batches(
    db_engine: AsyncEngine,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chain, "BATCH_SIZE", 2)
    client_id = await new_client(db_engine, settings, tmp_path)
    records = await build_chain(db_engine, client_id, 5)
    assert (await verify(db_engine, client_id)).records == 5
    async with log_unprotected(db_engine, client_id):
        await change_log(
            db_engine,
            "UPDATE evidence_log SET event_type = 'test.changed' WHERE id = :id",
            id=records[4].id,
        )
        result = await verify(db_engine, client_id)
    assert (result.failed_record_id, result.records) == (records[4].id, 5)


async def test_log_unprotected_puts_the_rows_back(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    client_id = await new_client(db_engine, settings, tmp_path)
    before = await build_chain(db_engine, client_id, 3)
    async with log_unprotected(db_engine, client_id):
        await change_log(
            db_engine, "DELETE FROM evidence_log WHERE client_id = :id", id=client_id
        )
    async with async_sessionmaker(db_engine)() as session:
        rows = (
            await session.execute(
                select(EvidenceLog.id, EvidenceLog.record_hash)
                .where(EvidenceLog.client_id == client_id)
                .order_by(EvidenceLog.id)
            )
        ).all()
    assert [tuple(row) for row in rows] == [(r.id, r.record_hash) for r in before]


def test_canonical_json_ignores_key_order_and_escapes_non_ascii() -> None:
    assert canonical_json({"b": 1, "a": [True, None]}) == '{"a":[true,null],"b":1}'
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert canonical_json({"name": "é"}) == '{"name":"\\u00e9"}'
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_json({"value": float("nan")})


def test_a_record_time_needs_a_time_zone_and_is_written_in_utc() -> None:
    with pytest.raises(ValueError, match="time zone"):
        iso_utc(datetime(2026, 10, 17, 12, 0))
    local = datetime(2026, 10, 17, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert iso_utc(local) == iso_utc(datetime(2026, 10, 17, 12, 0, tzinfo=UTC))
    assert iso_utc(local) == "2026-10-17T12:00:00.000000+00:00"


def test_the_hash_changes_when_any_part_of_the_record_changes() -> None:
    base = {
        "client_id": 1,
        "evidence_item_id": 2,
        "event_type": "evidence.added",
        "payload": {"n": 1},
        "previous_hash": GENESIS_HASH,
        "created_at": NOW,
    }
    reference = compute_record_hash(**base)
    changes = {
        "client_id": 3,
        "evidence_item_id": 4,
        "event_type": "evidence.revised",
        "payload": {"n": 2},
        "previous_hash": "1" * 64,
        "created_at": NOW + timedelta(microseconds=1),
    }
    for name, value in changes.items():
        assert compute_record_hash(**{**base, name: value}) != reference, name
