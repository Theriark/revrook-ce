"""Delete-per-client: everything of one client goes, the audit trail stays.

Removed: the client row with its key (so its pseudonyms can never be recomputed
or reversed), evidence items, revisions, facts, snapshots and exported packs,
and every file of the client. Kept: the append-only audit_event and
evidence_log rows, which hold ids, hashes and counts and no personal data. The
last record of the client's hash chain says the client was deleted, so the chain
still verifies afterwards.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import add_audit_event
from app.evidence.chain import append_record
from app.evidence.errors import EvidenceRejectedError
from app.evidence.files import FileStore
from app.evidence.locking import lock_client
from app.models import (
    Client,
    EvidenceItem,
    EvidenceRevision,
    Fact,
    ReportExport,
    Setting,
    Snapshot,
    draft_key,
)


@dataclass(frozen=True)
class DeletionReport:
    """What a deletion removed. Counts only."""

    client_id: int
    items: int
    revisions: int
    facts: int
    packs: int
    files: int


async def _count(session: AsyncSession, query: Select[Any]) -> int:
    return int((await session.execute(query)).scalar_one())


async def _delete_rows(
    session: AsyncSession,
    files: FileStore,
    client_id: int,
    confirm_name: str,
    actor_user_id: int | None,
    now: datetime,
) -> DeletionReport:
    client = await lock_client(session, client_id)
    if confirm_name.strip() != client.name:
        raise EvidenceRejectedError(
            "The confirmation does not match the client name. Nothing was deleted."
        )
    items = select(func.count()).select_from(EvidenceItem)
    revisions = (
        select(func.count())
        .select_from(EvidenceRevision)
        .join(EvidenceItem, EvidenceItem.id == EvidenceRevision.item_id)
    )
    facts = select(func.count()).select_from(Fact)
    snapshots = select(func.count()).select_from(Snapshot)
    exports = select(func.count()).select_from(ReportExport)
    item_count = await _count(session, items.where(EvidenceItem.client_id == client_id))
    revision_count = await _count(
        session, revisions.where(EvidenceItem.client_id == client_id)
    )
    fact_count = await _count(session, facts.where(Fact.client_id == client_id))
    snapshot_count = await _count(
        session, snapshots.where(Snapshot.client_id == client_id)
    )
    export_count = await _count(
        session, exports.where(ReportExport.client_id == client_id)
    )
    report = DeletionReport(
        client_id=client_id,
        items=item_count,
        revisions=revision_count,
        facts=fact_count,
        packs=snapshot_count + export_count,
        files=await asyncio.to_thread(files.count_client_files, client_id),
    )
    counts = {
        "items": report.items,
        "revisions": report.revisions,
        "facts": report.facts,
        "packs": report.packs,
        "files": report.files,
    }
    await append_record(
        session,
        client_id=client_id,
        event_type="client.deleted",
        payload=counts,
        now=now,
    )
    add_audit_event(
        session,
        "client.deleted",
        actor_user_id=actor_user_id,
        target_type="client",
        target_id=client_id,
        detail=counts,
    )
    # The draft notes of the client live in the setting table, with no foreign key.
    await session.execute(delete(Setting).where(Setting.key == draft_key(client_id)))
    # The foreign keys of every client table cascade, so this removes the rest.
    await session.execute(delete(Client).where(Client.id == client_id))
    return report


async def delete_client(
    session_factory: async_sessionmaker[AsyncSession],
    files: FileStore,
    client_id: int,
    *,
    confirm_name: str,
    actor_user_id: int | None,
    now: datetime,
) -> DeletionReport:
    """Delete a client for good. `confirm_name` must be the exact client name.

    The database part is one transaction. The files are removed after it has
    committed; if that fails, `remove_leftover_files` finishes the job.
    """
    async with session_factory() as session, session.begin():
        report = await _delete_rows(
            session, files, client_id, confirm_name, actor_user_id, now
        )
    await asyncio.to_thread(files.remove_client, client_id)
    return report


async def remove_leftover_files(session: AsyncSession, files: FileStore) -> list[int]:
    """Remove the folder of every client that no longer exists. Returns their ids."""
    on_disk = await asyncio.to_thread(files.client_ids_on_disk)
    if not on_disk:
        return []
    result = await session.execute(select(Client.id).where(Client.id.in_(on_disk)))
    existing = set(result.scalars())
    leftovers = [client_id for client_id in on_disk if client_id not in existing]
    for client_id in leftovers:
        await asyncio.to_thread(files.remove_client, client_id)
    return leftovers
