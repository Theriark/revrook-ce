"""Running the public DNS check for a client and reading what it found (phase 7).

`run_dns_check` asks the DNS for the mail domains the MSP entered, then stores the
answer as one automatic-export evidence item of the source `dns-check`: the
domains are pseudonymised (the same pseudonym as the `domain` of the Exchange DKIM
rows), the capture time is the time the run started, and the item goes into the
client's hash chain like any other evidence. The scheduled re-check of phase 10 and
the page of phase 9 call this function; it reads no clock of its own.

`dns_controls` is the checklist data: the results of PC-EML-01, PC-EML-02 and
PC-EML-03 from the newest `dns-check` item (and the newest Exchange export, which
PC-EML-02 also reads), each with the time the evidence was captured. A check whose
lookups failed is stored as such, so these controls are unknown for it, never a fail.
"""

import asyncio
import functools
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checks.dnscheck import (
    DnsCheck,
    Resolver,
    render_document,
    require_aware,
    run_checks,
)
from app.checks.engine import evaluate_control
from app.checks.library import Library
from app.checks.model import ControlResult, Evidence, SourceFacts
from app.evidence.assurance import Assurance
from app.evidence.errors import ClientNotFoundError
from app.evidence.service import (
    EvidenceContext,
    NewEvidence,
    StoredEvidence,
    add_evidence,
)
from app.importers.dnscheck import DnsCheckImporter
from app.importers.registry import ImporterRegistry
from app.models import Client, EvidenceItem, Fact

DNS_SOURCE = "dns-check"
EXCHANGE_SOURCE = "exchange-export"
DNS_CONTROLS = ("PC-EML-01", "PC-EML-02", "PC-EML-03")


async def require_client(session: AsyncSession, client_id: int) -> None:
    """Raises ClientNotFoundError unless the client exists."""
    if await session.get(Client, client_id) is None:
        raise ClientNotFoundError("There is no client with this id.")


async def look_up_dns(
    resolver: Resolver,
    domains: Sequence[str],
    selectors: Sequence[str] = (),
    providers: Sequence[str] = (),
    *,
    now: datetime,
) -> DnsCheck:
    """Ask the DNS for the mail domains of one client. No database is used.

    Raises ValueError for a naive `now` or an invalid domain, selector or provider;
    nothing is looked up then. The lookups run in a thread, so the event loop is not
    blocked while the DNS answers, and the run has a deadline (see `run_checks`).
    """
    require_aware(now, "now")
    run = functools.partial(
        run_checks, resolver, domains, selectors, providers, captured_at=now
    )
    return await asyncio.to_thread(run)


async def store_dns_check(
    session: AsyncSession,
    ctx: EvidenceContext,
    client_id: int,
    check: DnsCheck,
    *,
    now: datetime,
    actor_user_id: int | None = None,
) -> StoredEvidence:
    """Store a run as evidence of the client (ClientNotFoundError if it is gone)."""
    await require_client(session, client_id)
    registry = ImporterRegistry()
    registry.register(DnsCheckImporter())
    evidence = NewEvidence(
        source_code=DNS_SOURCE,
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=check.captured_at,
        data=render_document(check),
        uploader_id=actor_user_id,
    )
    return await add_evidence(
        session, replace(ctx, importers=registry), client_id, evidence, now
    )


async def run_dns_check(
    session: AsyncSession,
    ctx: EvidenceContext,
    client_id: int,
    resolver: Resolver,
    domains: Sequence[str],
    selectors: Sequence[str] = (),
    providers: Sequence[str] = (),
    *,
    now: datetime,
    actor_user_id: int | None = None,
) -> StoredEvidence:
    """Check the mail domains of one client and store the result as evidence.

    Raises ValueError for a naive `now` or an invalid domain, selector or provider,
    and ClientNotFoundError for an unknown client; nothing is looked up then.

    The caller's session stays open while the DNS answers, so a caller that must not
    hold a database connection that long (the API, the scheduler of phase 10) calls
    `require_client`, `look_up_dns` and `store_dns_check` itself, opening its
    transaction only for the last.
    """
    require_aware(now, "now")
    await require_client(session, client_id)
    check = await look_up_dns(resolver, domains, selectors, providers, now=now)
    return await store_dns_check(
        session, ctx, client_id, check, now=now, actor_user_id=actor_user_id
    )


async def load_source(
    session: AsyncSession, client_id: int, source_code: str
) -> SourceFacts | None:
    """The facts of the newest evidence item of one source; None if there is none."""
    newest = (
        select(EvidenceItem)
        .where(
            EvidenceItem.client_id == client_id,
            EvidenceItem.source_code == source_code,
        )
        .order_by(EvidenceItem.captured_at.desc(), EvidenceItem.id.desc())
        .limit(1)
    )
    item = (await session.execute(newest)).scalar_one_or_none()
    if item is None:
        return None
    rows = await session.execute(
        select(Fact.fact_key, Fact.value)
        .where(Fact.evidence_item_id == item.id)
        .order_by(Fact.id)
    )
    facts = [(key, value) for key, value in rows]
    return SourceFacts.from_facts(item.captured_at, facts)


async def dns_controls(
    session: AsyncSession, library: Library, client_id: int, as_of: datetime
) -> dict[str, ControlResult]:
    """PC-EML-01 to PC-EML-03 for one client at `as_of`, with their capture times.

    A source that was never imported is simply missing, and its controls are unknown
    with the reason licence_or_scope.
    """
    require_aware(as_of, "as_of")
    sources: dict[str, SourceFacts] = {}
    for code in (DNS_SOURCE, EXCHANGE_SOURCE):
        found = await load_source(session, client_id, code)
        if found is not None:
            sources[code] = found
    evidence = Evidence(as_of=as_of, sources=sources)
    return {
        control_id: evaluate_control(library, library.control(control_id), evidence)
        for control_id in DNS_CONTROLS
    }
