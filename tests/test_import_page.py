"""Import evidence: several files at once, each recognised by its content, and the
public DNS check from the evidence page (synthetic data only, no network)."""

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import devdata
from app.evidence.service import EvidenceContext
from app.importers.detect import AMBIGUOUS, NOT_RECOGNISED, Candidate, detect
from app.importers.generic import ADAPTERS as GENERIC
from app.importers.generic import DeviceInventoryAdapter
from app.importers.microsoft import ADAPTERS as MICROSOFT
from app.main import create_app
from app.models import EvidenceItem, Schedule
from app.settings import Settings
from dns_helpers import resolver_for, zone
from helpers import (
    FakeClock,
    create_admin,
    create_test_client,
    csrf_from,
    login,
    make_context,
)

CANDIDATES = [Candidate(adapter) for adapter in (*MICROSOFT, *GENERIC)]
CAPTURED = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
DOMAIN = "client.example"
GOOD_DNS = zone(
    DOMAIN,
    spf=["v=spf1 include:spf.protection.outlook.com -all"],
    dmarc=["v=DMARC1; p=reject"],
    cnames=["selector1"],
)


# --- recognising a file ------------------------------------------------------------


@pytest.mark.parametrize("profile", devdata.PROFILES)
def test_every_seed_file_is_recognised_as_its_own_source(profile: str) -> None:
    for seed in devdata.seed_files(profile, CAPTURED):
        found = detect(seed.data, CANDIDATES)
        assert found.candidate is not None, (seed.source_code, found.problem)
        assert found.candidate.adapter.source_code == seed.source_code


def test_an_empty_graph_answer_is_recognised_by_its_context() -> None:
    empty = {
        "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#identity/"
        "conditionalAccess/policies",
        "value": [],
    }
    found = detect(json.dumps(empty).encode(), CANDIDATES)
    assert found.candidate is not None
    assert found.candidate.adapter.source_code == "conditional-access"
    assert detect(b'{"value": []}', CANDIDATES).problem == NOT_RECOGNISED


def test_a_file_that_fits_no_source_is_not_guessed() -> None:
    found = detect(b"name,colour\nrook,black\n", CANDIDATES)
    assert found.candidate is None and found.problem == NOT_RECOGNISED


def test_a_saved_mapping_makes_a_vendor_file_recognised() -> None:
    vendor = (
        b"Asset,Platform,Seen,Patch,Critical,AV,AV state,AV date,Encrypted\n"
        b"pc-1,windows,2026-10-14T08:00:00Z,up_to_date,0,Defender,protected,"
        b"2026-10-14T08:00:00Z,true\n"
    )
    assert detect(vendor, CANDIDATES).problem == NOT_RECOGNISED
    mapping = {
        "Asset": "device_id",
        "Platform": "os",
        "Seen": "last_seen",
        "Patch": "patch_status",
        "Critical": "pending_critical_updates",
        "AV": "av_product",
        "AV state": "av_status",
        "AV date": "av_signature_date",
        "Encrypted": "disk_encrypted",
    }
    saved = Candidate(DeviceInventoryAdapter().with_mapping(mapping), profile_id=7)
    found = detect(vendor, [*CANDIDATES, saved])
    assert found.candidate == saved


def test_two_sources_that_fit_equally_well_are_not_guessed() -> None:
    twin = Candidate(DeviceInventoryAdapter())
    other = Candidate(
        type("Twin", (DeviceInventoryAdapter,), {"source_code": "twin"})()
    )
    data = devdata.seed_files(devdata.TIDY, CAPTURED)[5].data
    found = detect(data, [twin, other])
    assert found.candidate is None
    assert found.problem is not None
    assert found.problem.startswith(AMBIGUOUS.split("{")[0])


# --- the page -------------------------------------------------------------------------


@pytest.fixture
def page_settings(settings: Settings, tmp_path: Path) -> Settings:
    return replace(settings, evidence_dir=str(tmp_path / "evidence"))


@pytest.fixture
def web(page_settings: Settings, db_engine: AsyncEngine, clock: FakeClock) -> FastAPI:
    return create_app(page_settings, engine=db_engine, clock=clock)


@pytest.fixture
async def browser(web: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=web)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest.fixture
def ctx(page_settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(page_settings, tmp_path / "ctx")


async def signed_in(
    browser: httpx.AsyncClient, engine: AsyncEngine, ctx: EvidenceContext
) -> tuple[int, str]:
    await create_admin(engine)
    assert (await login(browser)).status_code == 303
    client_id = await create_test_client(engine, ctx)
    page = await browser.get(f"/imports?client_id={client_id}")
    assert page.status_code == 200, page.text
    assert "Import evidence" in page.text
    return client_id, csrf_from(page.text)


async def items_of(engine: AsyncEngine, client_id: int) -> list[str]:
    query = select(EvidenceItem.source_code).where(EvidenceItem.client_id == client_id)
    async with async_sessionmaker(engine)() as session:
        return sorted((await session.execute(query)).scalars())


async def test_several_files_are_imported_at_once_and_a_bad_one_stops_none(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    seeds = devdata.seed_files(devdata.TIDY, CAPTURED)
    files = [
        ("files", (f"{seed.source_code}.bin", seed.data, "application/octet-stream"))
        for seed in seeds
    ]
    files.append(("files", ("notes.csv", b"name,colour\nrook,black\n", "text/csv")))
    fields = {
        "csrf_token": csrf,
        "client_id": str(client_id),
        "captured_at": "2026-10-15T09:00",
    }
    answer = await browser.post("/imports", data=fields, files=files)
    assert answer.status_code == 200, answer.text
    assert f"{len(seeds)} of {len(seeds) + 1} files imported" in answer.text
    assert "notes.csv" in answer.text and "Not recognised" in answer.text
    assert await items_of(db_engine, client_id) == sorted(
        seed.source_code for seed in seeds
    )
    # The same files again are refused as duplicates, each on its own line.
    again = await browser.post("/imports", data=fields, files=files)
    assert again.status_code == 422
    assert "0 of" in again.text


async def test_an_import_without_files_is_refused(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    answer = await browser.post(
        "/imports",
        data={"csrf_token": csrf, "client_id": str(client_id)},
        files=[("other", ("x.txt", b"", "text/plain"))],
    )
    assert answer.status_code == 422
    assert "Choose at least one file to import." in answer.text


async def test_the_dns_check_runs_from_the_evidence_page_and_keeps_its_schedule(
    web: FastAPI,
    browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    resolver = resolver_for(GOOD_DNS)
    web.state.dns_resolver = resolver
    evidence = await browser.get(f"/clients/{client_id}/evidence")
    assert f'action="/clients/{client_id}/dns-check"' in evidence.text
    answer = await browser.post(
        f"/clients/{client_id}/dns-check",
        data={"csrf_token": csrf, "domains": f"{DOMAIN}", "weekly": "on"},
    )
    assert answer.status_code == 303
    assert answer.headers["location"].endswith("done=dns-weekly#dns-check")
    assert DOMAIN in resolver.names()
    assert await items_of(db_engine, client_id) == ["dns-check"]
    async with async_sessionmaker(db_engine)() as session:
        rows = (await session.execute(select(Schedule))).scalars().all()
    (schedule,) = [row for row in rows if row.client_id == client_id]
    assert schedule.kind == "dns-check" and schedule.enabled
    assert schedule.config["domains"] == [DOMAIN]
    shown = await browser.get(answer.headers["location"])
    assert "runs again every Monday" in shown.text
    assert f'value="{DOMAIN}"' in shown.text
    # Run again without the box: the weekly check is switched off, not deleted.
    resolver.answers[(DOMAIN, "TXT")] = [
        "v=spf1 include:spf.protection.outlook.com ~all"
    ]
    again = await browser.post(
        f"/clients/{client_id}/dns-check",
        data={"csrf_token": csrf, "domains": DOMAIN},
    )
    assert again.status_code == 303
    async with async_sessionmaker(db_engine)() as session:
        kept = await session.get(Schedule, schedule.id)
    assert kept is not None and kept.enabled is False


async def test_a_bad_mail_domain_is_refused_before_any_lookup(
    web: FastAPI,
    browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    resolver = resolver_for(GOOD_DNS)
    web.state.dns_resolver = resolver
    answer = await browser.post(
        f"/clients/{client_id}/dns-check",
        data={"csrf_token": csrf, "domains": "not a domain!"},
    )
    assert answer.status_code == 422
    assert resolver.queries == []
