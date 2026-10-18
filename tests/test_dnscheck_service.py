"""Running the DNS check for a client: stored as evidence, read as checklist data.

These tests need PostgreSQL (DATABASE_URL), like the other evidence tests; the
resolver is always a fake one and nothing reaches the network.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.dnscheck import TIMEOUT, LookupFailure
from app.checks.library import load_library
from app.checks.model import ControlResult
from app.clients import pseudonym_key
from app.dns_service import dns_controls, load_source, run_dns_check
from app.evidence.assurance import Assurance
from app.evidence.chain import verify_chain
from app.evidence.deletion import delete_client
from app.evidence.errors import ClientNotFoundError, EvidenceRejectedError
from app.evidence.service import EvidenceContext, NewEvidence, StoredEvidence
from app.models import Client, EvidenceItem, Fact
from app.pseudonym import pseudonymise
from app.settings import Settings
from dns_helpers import StaticResolver, resolver_for, zone
from helpers import NOW, create_test_client, database_dump, make_context, upload

LIBRARY = load_library()
DOMAIN = "client.example"
SPF = "v=spf1 include:spf.protection.outlook.com -all"
DMARC = "v=DMARC1; p=reject; rua=mailto:dmarc@client.example"
GOOD = zone(DOMAIN, spf=[SPF], dmarc=[DMARC], cnames=["selector1"])
WEAK = zone(DOMAIN, spf=["v=spf1 -all"], dmarc=["v=DMARC1; p=none"])
DOWN = {**GOOD, (DOMAIN, "TXT"): LookupFailure(TIMEOUT)}
EXCHANGE_CSV = b"record_type,domain,enabled\ndkim,client.example,true\n"
EXCHANGE_AT = NOW - timedelta(days=1)


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(settings, tmp_path)


def exchange_evidence() -> NewEvidence:
    return NewEvidence(
        source_code="exchange-export",
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=EXCHANGE_AT,
        data=EXCHANGE_CSV,
    )


async def check(
    engine: AsyncEngine,
    ctx: EvidenceContext,
    client_id: int,
    resolver: StaticResolver,
    *,
    domains: Sequence[str] = (DOMAIN,),
    selectors: Sequence[str] = (),
    providers: Sequence[str] = (),
    now: datetime = NOW,
) -> StoredEvidence:
    """Run the check in its own transaction, the way a caller would."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        return await run_dns_check(
            session,
            ctx,
            client_id,
            resolver,
            domains,
            selectors,
            providers,
            now=now,
        )


async def controls(
    engine: AsyncEngine, client_id: int, as_of: datetime = NOW
) -> dict[str, ControlResult]:
    async with async_sessionmaker(engine)() as session:
        return await dns_controls(session, LIBRARY, client_id, as_of)


async def items_of(engine: AsyncEngine, client_id: int) -> list[EvidenceItem]:
    query = select(EvidenceItem).where(EvidenceItem.client_id == client_id)
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(query.order_by(EvidenceItem.id))).scalars())


async def facts_of(engine: AsyncEngine, item_id: int) -> list[Fact]:
    query = select(Fact).where(Fact.evidence_item_id == item_id).order_by(Fact.id)
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(query)).scalars())


# --- stored as evidence ------------------------------------------------------------


async def test_the_result_is_stored_as_evidence_with_its_capture_time(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    stored = await check(db_engine, ctx, client_id, resolver_for(GOOD))
    assert stored.source_code == "dns-check"
    assert stored.assurance is Assurance.AUTOMATIC_EXPORT
    assert (stored.captured_at, stored.facts) == (NOW, 2)
    [item] = await items_of(db_engine, client_id)
    assert (item.captured_at, item.importer_version) == (NOW, "dns-check-1")
    assert item.status == "current" and item.expires_at is not None


async def test_the_domain_is_kept_only_as_the_pseudonym_of_the_client(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    stored = await check(db_engine, ctx, client_id, resolver_for(GOOD))
    async with async_sessionmaker(db_engine)() as session:
        client = await session.get(Client, client_id)
    assert client is not None
    expected = pseudonymise(pseudonym_key(ctx.cipher, client), DOMAIN)
    [domain, summary] = await facts_of(db_engine, stored.item_id)
    assert domain.fact_key == "dns.domain" and domain.value["domain"] == expected
    assert summary.fact_key == "dns.summary"
    dump = await database_dump(db_engine)
    assert DOMAIN not in dump and "dmarc@" not in dump
    assert expected in dump


async def test_the_pseudonym_is_the_one_of_the_exchange_dkim_rows(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    await upload(db_engine, ctx, client_id, exchange_evidence())
    await check(db_engine, ctx, client_id, resolver_for(GOOD))
    async with async_sessionmaker(db_engine)() as session:
        dns = await load_source(session, client_id, "dns-check")
        exchange = await load_source(session, client_id, "exchange-export")
    assert dns is not None and exchange is not None
    assert dns.rows("domain")[0]["domain"] == exchange.rows("dkim")[0]["domain"]


async def test_another_client_gets_another_pseudonym_for_the_same_domain(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    first = await create_test_client(db_engine, ctx, "First Client Ltd")
    second = await create_test_client(db_engine, ctx, "Second Client Ltd")
    names = []
    for client_id in (first, second):
        stored = await check(db_engine, ctx, client_id, resolver_for(GOOD))
        [domain, _] = await facts_of(db_engine, stored.item_id)
        names.append(domain.value["domain"])
    assert names[0] != names[1]


async def test_the_hash_chain_still_verifies_after_a_check(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    await check(db_engine, ctx, client_id, resolver_for(GOOD))
    async with async_sessionmaker(db_engine)() as session:
        result = await verify_chain(session, client_id)
    assert result.ok and result.records >= 1


async def test_nobody_can_upload_a_dns_check_file_by_hand(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    forged = NewEvidence(
        source_code="dns-check",
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=NOW,
        data=b'{"capturedAt":"2026-10-17T12:00:00+00:00","domains":[]}',
    )
    with pytest.raises(EvidenceRejectedError, match="no importer for the source"):
        await upload(db_engine, ctx, client_id, forged)
    assert await items_of(db_engine, client_id) == []


# --- read as checklist data --------------------------------------------------------


async def test_the_controls_read_the_stored_facts_with_their_capture_time(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    await upload(db_engine, ctx, client_id, exchange_evidence())
    await check(db_engine, ctx, client_id, resolver_for(GOOD))
    found = await controls(db_engine, client_id)
    assert {key: item.status for key, item in found.items()} == {
        "PC-EML-01": "pass",
        "PC-EML-02": "pass",
        "PC-EML-03": "pass",
    }
    assert found["PC-EML-01"].evidence_at == NOW
    assert found["PC-EML-03"].evidence_at == NOW
    assert found["PC-EML-02"].evidence_at == EXCHANGE_AT, "the older of two sources"


async def test_the_newest_check_is_the_one_that_counts(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    await check(db_engine, ctx, client_id, resolver_for(WEAK))
    weak = await controls(db_engine, client_id)
    assert weak["PC-EML-01"].status == "fail" and weak["PC-EML-03"].status == "fail"
    later = NOW + timedelta(days=1)
    await check(db_engine, ctx, client_id, resolver_for(GOOD), now=later)
    better = await controls(db_engine, client_id, later)
    assert better["PC-EML-01"].status == "pass"
    assert better["PC-EML-03"].evidence_at == later
    assert len(await items_of(db_engine, client_id)) == 2


async def test_a_failed_lookup_is_stored_and_the_controls_are_unknown_not_fail(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    await check(db_engine, ctx, client_id, resolver_for(GOOD))
    later = NOW + timedelta(hours=1)
    stored = await check(db_engine, ctx, client_id, resolver_for(DOWN), now=later)
    [domain, summary] = await facts_of(db_engine, stored.item_id)
    assert domain.value["lookup_failed"] is True
    assert domain.value["lookup_reason"] == "timeout"
    assert domain.value["spf_records"] is None
    assert summary.value["lookups_failed"] == 1
    found = await controls(db_engine, client_id, later)
    for control_id in ("PC-EML-01", "PC-EML-03"):
        result = found[control_id]
        assert (result.status, result.reason) == ("unknown", "lookup_failed")
        assert result.evidence_at == later


async def test_a_client_without_a_check_has_unknown_controls(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    found = await controls(db_engine, client_id)
    for result in found.values():
        assert (result.status, result.reason) == ("unknown", "licence_or_scope")
    async with async_sessionmaker(db_engine)() as session:
        assert await load_source(session, client_id, "dns-check") is None


async def test_a_naive_as_of_is_refused(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    with pytest.raises(ValueError, match="as_of must carry a timezone"):
        await controls(db_engine, client_id, NOW.replace(tzinfo=None))


# --- refusals ----------------------------------------------------------------------


async def test_an_unknown_client_is_refused_before_any_lookup(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    resolver = resolver_for(GOOD)
    with pytest.raises(ClientNotFoundError):
        await check(db_engine, ctx, 987_654_321, resolver)
    assert resolver.queries == []


@pytest.mark.parametrize(
    "options",
    [
        {"domains": ["not a domain"]},
        {"domains": []},
        {"selectors": ["bad selector"]},
        {"providers": ["nope"]},
        {"now": NOW.replace(tzinfo=None)},
    ],
    ids=["domain", "no-domain", "selector", "provider", "naive-time"],
)
async def test_a_refused_input_looks_nothing_up_and_stores_nothing(
    db_engine: AsyncEngine, ctx: EvidenceContext, options: dict[str, object]
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    resolver = resolver_for(GOOD)
    with pytest.raises(ValueError):
        await check(db_engine, ctx, client_id, resolver, **options)
    assert resolver.queries == []
    assert await items_of(db_engine, client_id) == []


async def test_deleting_the_client_deletes_its_dns_facts(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx, "Delete Me Ltd")
    await check(db_engine, ctx, client_id, resolver_for(GOOD))
    report = await delete_client(
        async_sessionmaker(db_engine, expire_on_commit=False),
        ctx.files,
        client_id,
        confirm_name="Delete Me Ltd",
        actor_user_id=None,
        now=NOW,
    )
    assert (report.items, report.facts) == (1, 2)
    assert await items_of(db_engine, client_id) == []
    assert DOMAIN not in await database_dump(db_engine)
