"""The jobs a schedule row can name. Each takes the claimed row and the run time.

* `dns-check`: look up the SPF, DKIM and DMARC records of the mail domains in the
  schedule's config and store the answer as evidence of its client.
* `expiry-reminder`: one message about every item that crossed a reminder threshold.
* `retention-purge`: raw files, old packs and leftover folders (`app.worker.purge`).
* `snapshot-build`: store the state of the client today as a snapshot, for the last
  full quarter. It is how a snapshot is built on request without a browser.

A job returns a short sentence for the log. It raises when it failed; the scheduler
logs the class of the error and writes an audit event.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import add_audit_event
from app.checks.dnscheck import Resolver
from app.checks.library import Library, load_library
from app.clock import Clock, utcnow
from app.crypto import FieldCipher
from app.dns_resolver import make_resolver
from app.dns_service import look_up_dns, require_client, store_dns_check
from app.evidence.errors import DuplicateEvidenceError
from app.evidence.files import FileStore
from app.evidence.locking import lock_client
from app.evidence.service import EvidenceContext
from app.importers.registry import build_default_registry
from app.posture import load_live
from app.preferences import get_reminder_recipient
from app.settings import Settings
from app.snapshots import recent_twin, store_snapshot
from app.ui.common import last_quarter
from app.worker.mail import mail_configured, send_mail
from app.worker.purge import run_purge
from app.worker.reminders import (
    SUBJECT,
    claim_reminders,
    compose_message,
    due_reminders,
    release_reminders,
)
from app.worker.scheduler import (
    DNS_CHECK,
    EXPIRY_REMINDER,
    RETENTION_PURGE,
    SNAPSHOT_BUILD,
    DueSchedule,
    Job,
)

Mailer = Callable[[Settings, str, str, str], None]


@dataclass(frozen=True)
class JobContext:
    """Everything the jobs need. Tests give it a fake resolver and a fake mailer."""

    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings
    evidence: EvidenceContext
    library: Library
    resolver: Resolver
    mailer: Mailer
    # The time of a claim is read when it is made, not taken from the start of the
    # run: a job may start long after the run did. Without a clock the run time
    # is used (tests that fix the time).
    clock: Clock | None = None


def make_job_context(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> JobContext:
    """The context of a real worker, built from its settings."""
    return JobContext(
        session_factory=session_factory,
        settings=settings,
        evidence=EvidenceContext(
            files=FileStore(settings.evidence_dir),
            cipher=FieldCipher(settings.fernet_key),
            importers=build_default_registry(),
            settings=settings,
        ),
        library=load_library(),
        resolver=make_resolver(settings.dns_resolver),
        mailer=send_mail,
        clock=utcnow,
    )


def _strings(config: dict[str, Any], key: str) -> list[str]:
    """A list of texts from the config of a schedule; ValueError when it is not."""
    value = config.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"the {key} of the schedule must be a list of texts")
    return value


def _client_of(due: DueSchedule) -> int:
    if due.client_id is None:
        raise ValueError(f"a {due.kind} schedule needs a client")
    return due.client_id


def build_jobs(ctx: JobContext) -> dict[str, Job]:
    """The job of each kind of schedule, bound to one context."""

    async def dns_check(due: DueSchedule, now: datetime) -> str:
        client_id = _client_of(due)
        async with ctx.session_factory() as session:
            await require_client(session, client_id)
        # No database connection is held while the DNS answers.
        check = await look_up_dns(
            ctx.resolver,
            _strings(due.config, "domains"),
            _strings(due.config, "selectors"),
            _strings(due.config, "providers"),
            now=now,
        )
        try:
            async with ctx.session_factory() as session, session.begin():
                stored = await store_dns_check(
                    session, ctx.evidence, client_id, check, now=now
                )
        except DuplicateEvidenceError:
            return "the same answer was already stored"
        return f"stored evidence item {stored.item_id}"

    async def expiry_reminder(due: DueSchedule, now: datetime) -> str:
        async with ctx.session_factory() as session:
            recipient = await get_reminder_recipient(session)
        if recipient is None or not mail_configured(ctx.settings):
            return "skipped: no reminder address or no mail relay is set"
        async with ctx.session_factory() as session, session.begin():
            due_now = await due_reminders(session, now)
            claimed_at = now if ctx.clock is None else ctx.clock()
            claimed = await claim_reminders(session, due_now, claimed_at)
        if not claimed:
            return "nothing is due"
        try:
            await asyncio.to_thread(
                ctx.mailer,
                ctx.settings,
                recipient,
                SUBJECT,
                compose_message(claimed),
            )
        except Exception:
            # The message did not leave, so the thresholds are free to be sent again.
            async with ctx.session_factory() as session, session.begin():
                await release_reminders(session, claimed)
            raise
        thresholds = sorted({days for item in claimed for days in item.thresholds})
        async with ctx.session_factory() as session, session.begin():
            add_audit_event(
                session,
                "reminder.sent",
                detail={
                    "items": len(claimed),
                    "clients": len({item.client_name for item in claimed}),
                    "thresholds": thresholds,
                },
            )
        return f"sent {len(claimed)} reminders in one message"

    async def retention_purge(due: DueSchedule, now: datetime) -> str:
        result = await run_purge(
            ctx.session_factory,
            ctx.evidence.files,
            now,
            ctx.settings.pack_retention_months,
        )
        return f"removed {result.summary()}"

    async def snapshot_build(due: DueSchedule, now: datetime) -> str:
        client_id = _client_of(due)
        start, end = last_quarter(now.date())
        async with ctx.session_factory() as session, session.begin():
            await lock_client(session, client_id)
            live = await load_live(session, ctx.library, client_id, now)
            twin = await recent_twin(session, client_id, live.snapshot, start, end)
            if twin is not None:
                return f"snapshot {twin} already holds this state"
            snapshot_id = await store_snapshot(
                session, client_id, live.snapshot, start, end
            )
            add_audit_event(
                session,
                "snapshot.created",
                target_type="snapshot",
                target_id=snapshot_id,
                detail={"client_id": client_id, "by": "worker"},
            )
        return f"stored snapshot {snapshot_id}"

    return {
        DNS_CHECK: dns_check,
        EXPIRY_REMINDER: expiry_reminder,
        RETENTION_PURGE: retention_purge,
        SNAPSHOT_BUILD: snapshot_build,
    }
