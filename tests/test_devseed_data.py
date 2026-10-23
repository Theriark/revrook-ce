"""The synthetic clients of the Development seed (app/devseed.py; THE-953).

Every source of the product has evidence on a seeded client, a client is made once
by its name, a failure in one client leaves the others as they were, and the pages
that read the data answer on it. Synthetic data only; no password appears here.
"""

import logging
from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import devdata, devseed
from app.checks.library import Library, load_library
from app.evidence.assurance import Assurance
from app.evidence.errors import EvidenceError
from app.evidence.service import EvidenceContext
from app.models import Client, EvidenceItem, Snapshot
from app.settings import Settings
from app.sources import SOURCE_NAMES
from helpers import NOW
from html_structure import structure_problems
from ui_helpers import sign_in

LIBRARY = load_library()
NAMES = tuple(client.name for client in devseed.DEMO_CLIENTS)
TIDY, GAPS, STALE, EMPTY = NAMES
DEV_URL = "https://ce-dev-revrook.theriark.dev"
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"


async def make(engine: AsyncEngine, ctx: EvidenceContext) -> devseed.DemoResult:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return await devseed.seed_demo_data(factory, ctx, LIBRARY, NOW)


async def ids_by_name(engine: AsyncEngine) -> dict[str, int]:
    async with async_sessionmaker(engine)() as session:
        rows = await session.execute(select(Client.name, Client.id))
        return {name: client_id for name, client_id in rows.all()}


async def count(engine: AsyncEngine, column: object) -> int:
    async with async_sessionmaker(engine)() as session:
        return int((await session.execute(select(func.count(column)))).scalar_one())


async def items_of(engine: AsyncEngine, client_id: int) -> list[EvidenceItem]:
    async with async_sessionmaker(engine)() as session:
        found = await session.execute(
            select(EvidenceItem).where(EvidenceItem.client_id == client_id)
        )
        return list(found.scalars())


async def test_every_source_has_evidence_on_a_seeded_client(
    db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    result = await make(db_engine, ui_ctx)
    assert result.created == NAMES and result.unchanged == ()
    ids = await ids_by_name(db_engine)
    assert set(ids) == set(NAMES)
    items = await items_of(db_engine, ids[TIDY])
    automatic = {
        item.source_code
        for item in items
        if item.assurance_level == Assurance.AUTOMATIC_EXPORT
    }
    assert automatic == set(SOURCE_NAMES)
    levels = {item.assurance_level for item in items}
    assert levels == {level.value for level in Assurance}
    # Three rounds of every source, and the two manual items.
    assert len(items) == 3 * len(SOURCE_NAMES) + 2
    gaps = {item.source_code for item in await items_of(db_engine, ids[GAPS])}
    assert gaps == set(SOURCE_NAMES)
    stale = await items_of(db_engine, ids[STALE])
    assert {item.source_code for item in stale} == set(
        next(c for c in devseed.DEMO_CLIENTS if c.name == STALE).sources
    )
    assert await items_of(db_engine, ids[EMPTY]) == []
    assert result.evidence == await count(db_engine, EvidenceItem.id)


async def test_a_second_run_changes_nothing(
    db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await make(db_engine, ui_ctx)
    before = (
        await count(db_engine, Client.id),
        await count(db_engine, EvidenceItem.id),
        await count(db_engine, Snapshot.id),
    )
    again = await make(db_engine, ui_ctx)
    assert again.created == () and again.unchanged == NAMES
    assert again.evidence == 0 and again.reports == 0
    after = (
        await count(db_engine, Client.id),
        await count(db_engine, EvidenceItem.id),
        await count(db_engine, Snapshot.id),
    )
    assert after == before


async def test_the_reports_give_the_history_charts_something_to_draw(
    db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    result = await make(db_engine, ui_ctx)
    ids = await ids_by_name(db_engine)
    assert result.reports == 7
    async with async_sessionmaker(db_engine)() as session:
        found = await session.execute(
            select(Snapshot.client_id, Snapshot.as_of).order_by(Snapshot.as_of)
        )
        moments: dict[int, list[object]] = {}
        for client_id, as_of in found.all():
            moments.setdefault(client_id, []).append(as_of)
    assert len(moments[ids[TIDY]]) == len(set(moments[ids[TIDY]])) == 3
    assert len(moments[ids[GAPS]]) == 3 and len(moments[ids[STALE]]) == 1
    assert ids[EMPTY] not in moments


async def test_a_failure_leaves_the_clients_made_before_it_and_a_rerun_finishes(
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = devseed.seed_stage

    async def fail_for_gaps(
        session: AsyncSession,
        ctx: EvidenceContext,
        library: Library,
        client: devseed.DemoClient,
        stage: devseed.Stage,
        client_id: int,
        now: datetime,
    ) -> tuple[int, int]:
        if client.name == GAPS:
            raise EvidenceError("synthetic failure")
        return await real(session, ctx, library, client, stage, client_id, now)

    monkeypatch.setattr(devseed, "seed_stage", fail_for_gaps)
    with pytest.raises(EvidenceError):
        await make(db_engine, ui_ctx)
    assert set(await ids_by_name(db_engine)) == {TIDY}
    monkeypatch.setattr(devseed, "seed_stage", real)
    rerun = await make(db_engine, ui_ctx)
    assert rerun.unchanged == (TIDY,) and rerun.created == (GAPS, STALE, EMPTY)


async def test_the_pages_answer_on_the_seeded_clients(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    await make(db_engine, ui_ctx)
    ids = await ids_by_name(db_engine)
    listing = await ui_browser.get("/clients")
    assert listing.status_code == 200 and structure_problems(listing.text) == []
    for name in NAMES:
        assert name in listing.text
    home = await ui_browser.get("/")
    assert home.status_code == 200 and structure_problems(home.text) == []
    for name in NAMES:
        client_id = ids[name]
        for path in ("", "/checklist", "/evidence", "/reports?span=all", "/exports"):
            page = await ui_browser.get(f"/clients/{client_id}{path}")
            assert page.status_code == 200, (name, path)
            assert structure_problems(page.text) == [], (name, path)
    evidence = await ui_browser.get(f"/clients/{ids[TIDY]}/evidence")
    for code in SOURCE_NAMES:
        assert SOURCE_NAMES[code] in evidence.text, code
    history = await ui_browser.get(f"/clients/{ids[TIDY]}/reports?span=all")
    assert 'id="history-empty"' not in history.text
    assert 'id="history-capped"' not in history.text


def test_the_data_is_on_unless_dev_seed_data_is_zero() -> None:
    assert devseed.data_enabled({})
    assert devseed.data_enabled({"DEV_SEED": "1"})
    assert devseed.data_enabled({"DEV_SEED_DATA": "1"})
    assert not devseed.data_enabled({"DEV_SEED_DATA": "0"})
    assert not devseed.data_enabled({"DEV_SEED_DATA": " 0 "})


def test_the_data_follows_the_same_environment_rules_as_the_accounts(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    stage_url = "https://ce-stg-revrook.theriark.dev"
    elsewhere = replace(settings, base_url=stage_url, database_url=UNREACHABLE)
    devseed.run_dev_seed(elsewhere, {"DEV_SEED": "1"})
    assert "dev seed: refused" in caplog.text and "failed" not in caplog.text
    caplog.clear()
    development = replace(settings, base_url=DEV_URL, database_url=UNREACHABLE)
    devseed.run_dev_seed(development, {"DEV_SEED": "1", "DEV_SEED_DATA": "0"})
    assert "data failed" not in caplog.text
    devseed.run_dev_seed(development, {"DEV_SEED": "1"})
    assert "dev seed: data failed" in caplog.text


def test_the_demo_clients_are_distinct_and_use_known_profiles() -> None:
    assert len(set(NAMES)) == len(NAMES)
    for client in devseed.DEMO_CLIENTS:
        assert set(client.sources) <= set(devdata.SOURCES)
        for stage in client.stages:
            assert stage.profile in devdata.PROFILES
            assert stage.report_days is None or stage.report_days <= stage.age_days
