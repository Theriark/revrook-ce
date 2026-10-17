"""The evidence log hash chain: one chain per client, verified record by record.

Every record stores the hash of the record before it (the first record of a
client stores 64 zeros) and its own hash, the SHA-256 of a canonical JSON text
of its client, item, event type, payload, previous hash and creation time.

What this proves: nothing in the log changed since it was written, and no
record in the middle was removed or reordered. What it does not prove: that the
data in the source portal was true; or that the newest records were not cut
off the end of the chain (keep the head hash that `revrook verify-chain`
prints if you need that). The database triggers of revision 0002 already
refuse UPDATE and DELETE; the chain detects a change made by someone who
switched the triggers off.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EvidenceLog

GENESIS_HASH = "0" * 64
BATCH_SIZE = 500

PREVIOUS_MISMATCH = "the record does not follow the record before it"
CONTENT_MISMATCH = "the record content does not match its hash"


@dataclass(frozen=True)
class ChainResult:
    """The outcome of verifying one client's chain."""

    client_id: int
    ok: bool
    records: int
    head_hash: str
    failed_record_id: int | None = None
    reason: str | None = None


def canonical_json(value: object) -> str:
    """One exact text for a JSON value: sorted keys, no spaces, ASCII only."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def iso_utc(moment: datetime) -> str:
    """A timestamp as UTC text with microseconds, the form that is hashed."""
    if moment.tzinfo is None:
        raise ValueError("a record time must carry a time zone")
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def compute_record_hash(
    *,
    client_id: int | None,
    evidence_item_id: int | None,
    event_type: str,
    payload: Mapping[str, object],
    previous_hash: str,
    created_at: datetime,
) -> str:
    text = canonical_json(
        {
            "client_id": client_id,
            "evidence_item_id": evidence_item_id,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": iso_utc(created_at),
        }
    )
    return hashlib.sha256(text.encode("ascii")).hexdigest()


async def head_hash(session: AsyncSession, client_id: int) -> str:
    """The hash of the newest record of a client (zeros for an empty chain)."""
    newest = (
        await session.execute(
            select(EvidenceLog.record_hash)
            .where(EvidenceLog.client_id == client_id)
            .order_by(EvidenceLog.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return GENESIS_HASH if newest is None else newest


async def append_record(
    session: AsyncSession,
    *,
    client_id: int,
    event_type: str,
    payload: Mapping[str, object],
    now: datetime,
    evidence_item_id: int | None = None,
) -> EvidenceLog:
    """Append one record to the client's chain.

    The caller holds the client row lock (app.evidence.service.lock_client), so
    two writers cannot both extend the same record. The payload holds ids,
    hashes and counts, never a personal identifier or a file name.
    """
    previous = await head_hash(session, client_id)
    record = EvidenceLog(
        client_id=client_id,
        evidence_item_id=evidence_item_id,
        event_type=event_type,
        payload=dict(payload),
        previous_hash=previous,
        record_hash=compute_record_hash(
            client_id=client_id,
            evidence_item_id=evidence_item_id,
            event_type=event_type,
            payload=payload,
            previous_hash=previous,
            created_at=now,
        ),
        created_at=now,
    )
    session.add(record)
    await session.flush()
    return record


async def verify_chain(session: AsyncSession, client_id: int) -> ChainResult:
    """Check every record of one client, oldest first, and stop at the first bad one.

    A changed record is reported at that record. A removed record is reported at
    the record after it, because that one no longer follows its predecessor.
    """
    expected_previous = GENESIS_HASH
    records = 0
    last_id = 0
    while True:
        batch = (
            await session.execute(
                select(
                    EvidenceLog.id,
                    EvidenceLog.evidence_item_id,
                    EvidenceLog.event_type,
                    EvidenceLog.payload,
                    EvidenceLog.previous_hash,
                    EvidenceLog.record_hash,
                    EvidenceLog.created_at,
                )
                .where(EvidenceLog.client_id == client_id, EvidenceLog.id > last_id)
                .order_by(EvidenceLog.id)
                .limit(BATCH_SIZE)
            )
        ).all()
        if not batch:
            return ChainResult(
                client_id=client_id,
                ok=True,
                records=records,
                head_hash=expected_previous,
            )
        for row_id, item_id, event_type, payload, previous, current, created in batch:
            records += 1
            last_id = row_id
            if previous != expected_previous:
                return ChainResult(
                    client_id=client_id,
                    ok=False,
                    records=records,
                    head_hash=expected_previous,
                    failed_record_id=row_id,
                    reason=PREVIOUS_MISMATCH,
                )
            recomputed = compute_record_hash(
                client_id=client_id,
                evidence_item_id=item_id,
                event_type=event_type,
                payload=payload,
                previous_hash=previous,
                created_at=created,
            )
            if recomputed != current:
                return ChainResult(
                    client_id=client_id,
                    ok=False,
                    records=records,
                    head_hash=expected_previous,
                    failed_record_id=row_id,
                    reason=CONTENT_MISMATCH,
                )
            expected_previous = current


async def chained_client_ids(session: AsyncSession) -> list[int]:
    """Every client id that has records in the log, deleted clients included."""
    result = await session.execute(
        select(EvidenceLog.client_id)
        .where(EvidenceLog.client_id.is_not(None))
        .distinct()
        .order_by(EvidenceLog.client_id)
    )
    return [client_id for client_id in result.scalars() if client_id is not None]


async def verify_all(session: AsyncSession) -> list[ChainResult]:
    """Verify the chain of every client in the log."""
    return [
        await verify_chain(session, client_id)
        for client_id in await chained_client_ids(session)
    ]
