"""Raw-file retention: deleting raw uploads once their retention date has passed.

A raw export is parsed on upload. With RAW_RETENTION_DAYS=0 (the default) no
raw file is ever written. With a value of 1 to 35 the file is kept for that many
days (for re-parsing after a parser fix) and removed here afterwards; its hash
stays in the evidence log. Manual artefacts are evidence in their own right and
carry no raw retention date. Pack retention (default 25 months) is computed by
`app.evidence.expiry.pack_expires_at`; the purge of packs arrives with the
worker in phase 10.
"""

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.evidence.chain import append_record
from app.evidence.errors import ClientNotFoundError
from app.evidence.files import FileStore
from app.evidence.locking import lock_client
from app.models import EvidenceItem, EvidenceRevision

PURGE_BATCH_SIZE = 500


async def purge_expired_raw(
    session: AsyncSession, files: FileStore, now: datetime
) -> int:
    """Delete raw files whose retention date has passed. Returns how many.

    Each purge is a chain record and an audit event. At most PURGE_BATCH_SIZE
    files are handled per call; the caller commits.
    """
    due = (
        await session.execute(
            select(
                EvidenceRevision.id,
                EvidenceRevision.item_id,
                EvidenceItem.client_id,
            )
            .join(EvidenceItem, EvidenceItem.id == EvidenceRevision.item_id)
            .where(
                EvidenceRevision.storage_key.is_not(None),
                EvidenceRevision.raw_expires_at <= now,
            )
            .order_by(EvidenceItem.client_id, EvidenceRevision.id)
            .limit(PURGE_BATCH_SIZE)
        )
    ).all()
    purged = 0
    for revision_id, item_id, client_id in due:
        try:
            await lock_client(session, client_id)
        except ClientNotFoundError:
            continue
        revision = await session.get(EvidenceRevision, revision_id)
        if revision is None or revision.storage_key is None:
            continue
        await asyncio.to_thread(files.remove, revision.storage_key)
        revision.storage_key = None
        await append_record(
            session,
            client_id=client_id,
            event_type="evidence.raw_purged",
            payload={
                "item_id": item_id,
                "revision": revision.revision_number,
                "sha256": revision.sha256,
            },
            now=now,
            evidence_item_id=item_id,
        )
        add_audit_event(
            session,
            "evidence.raw_purged",
            target_type="evidence_item",
            target_id=item_id,
            detail={"client_id": client_id, "revision": revision.revision_number},
        )
        purged += 1
    return purged
