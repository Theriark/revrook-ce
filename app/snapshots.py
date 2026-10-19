"""Stored snapshots: the inputs of a score, kept so a report can be made again.

A snapshot row holds the canonical document of `app/scoring/snapshot.py` (the inputs,
the results and the digest of both) in the `inputs` column, and the period the report
is about. Reading it back gives the bytes that were written, because the document is
plain JSON with sorted keys and no float. The digest in it is checked whenever a
report is built, so a row that was edited is refused.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.errors import EvidenceError
from app.models import Snapshot
from app.scoring.snapshot import SnapshotInput, document_bytes, snapshot_document

MAX_LISTED = 20
DOUBLE_SUBMIT_SECONDS = 30


class SnapshotNotFoundError(EvidenceError):
    """There is no such snapshot for this client."""


@dataclass(frozen=True)
class SnapshotLine:
    """One snapshot in a list."""

    id: int
    period_start: date
    period_end: date
    as_of: datetime
    created_at: datetime


async def store_snapshot(
    session: AsyncSession,
    client_id: int,
    snapshot: SnapshotInput,
    period_start: date,
    period_end: date,
) -> int:
    """Keep a snapshot for a client and return its id."""
    row = Snapshot(
        client_id=client_id,
        period_start=period_start,
        period_end=period_end,
        as_of=snapshot.as_of,
        ruleset_version=snapshot.ruleset_version,
        importer_versions={"summary": snapshot.importer_version},
        inputs=snapshot_document(snapshot),
    )
    session.add(row)
    await session.flush()
    return row.id


async def recent_twin(
    session: AsyncSession,
    client_id: int,
    snapshot: SnapshotInput,
    period_start: date,
    period_end: date,
) -> int | None:
    """The id of the snapshot a double submit of the same form just made, or None.

    It is the newest snapshot of the client when it has the same period, was made at
    most DOUBLE_SUBMIT_SECONDS earlier and holds the same inputs and results once its
    own moment is used. The caller holds the client's lock, so two posts in flight
    are serialised and the second finds the first.
    """
    found = await session.execute(
        select(Snapshot)
        .where(Snapshot.client_id == client_id)
        .order_by(Snapshot.id.desc())
        .limit(1)
    )
    row = found.scalar_one_or_none()
    if row is None or (row.period_start, row.period_end) != (period_start, period_end):
        return None
    age = snapshot.as_of - row.as_of
    if not timedelta(0) <= age <= timedelta(seconds=DOUBLE_SUBMIT_SECONDS):
        return None
    if snapshot_document(replace(snapshot, as_of=row.as_of)) != row.inputs:
        return None
    return row.id


async def load_snapshot(
    session: AsyncSession, client_id: int, snapshot_id: int
) -> tuple[Snapshot, bytes]:
    """A snapshot of this client and its bytes; SnapshotNotFoundError otherwise."""
    row = await session.get(Snapshot, snapshot_id)
    if row is None or row.client_id != client_id:
        raise SnapshotNotFoundError("There is no such snapshot for this client.")
    return row, document_bytes(row.inputs)


async def earlier_bytes(
    session: AsyncSession,
    client_id: int,
    before: datetime | None = None,
    exclude_id: int | None = None,
) -> bytes | None:
    """The newest snapshot of the client (made before `before`, if given), as bytes."""
    query = select(Snapshot).where(Snapshot.client_id == client_id)
    if before is not None:
        query = query.where(Snapshot.as_of < before)
    if exclude_id is not None:
        query = query.where(Snapshot.id != exclude_id)
    found = await session.execute(
        query.order_by(Snapshot.as_of.desc(), Snapshot.id.desc()).limit(1)
    )
    row = found.scalar_one_or_none()
    return None if row is None else document_bytes(row.inputs)


async def list_snapshots(session: AsyncSession, client_id: int) -> list[SnapshotLine]:
    """The newest snapshots of the client, without their documents."""
    found = await session.execute(
        select(
            Snapshot.id,
            Snapshot.period_start,
            Snapshot.period_end,
            Snapshot.as_of,
            Snapshot.created_at,
        )
        .where(Snapshot.client_id == client_id)
        .order_by(Snapshot.id.desc())
        .limit(MAX_LISTED)
    )
    return [
        SnapshotLine(item_id, start, end, as_of, created)
        for item_id, start, end, as_of, created in found.all()
    ]
