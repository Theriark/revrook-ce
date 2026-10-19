"""The scheduler, the worker loop, the stale banner and the schedules API (phase 10).

These tests need PostgreSQL (DATABASE_URL), like the other worker tests. Time is a
fake clock and the jobs are counters or fakes: nothing here reaches the network.
"""

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Schedule, WorkerHeartbeat
from app.settings import Settings
from app.worker import run_worker
from app.worker.cron import next_run_for
from app.worker.heartbeat import NEVER, RUNNING, STALE, STALE_AFTER, beat, read_status
from app.worker.scheduler import (
    DEFAULT_SCHEDULES,
    DNS_CHECK,
    RETENTION_PURGE,
    DueSchedule,
    Job,
    ensure_default_schedules,
    run_due,
    start_unscheduled,
)
from helpers import NOW, FakeClock, audit_baseline, audit_since, issue_token
from ui_helpers import sign_in

EVERY_FIVE = "*/5 * * * *"
BANNER = 'id="worker-banner"'


def factory_of(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class Counter:
    """A job that records each run. `delay` keeps it busy, so runs can overlap."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.runs: list[tuple[str, datetime]] = []

    async def __call__(self, due: DueSchedule, now: datetime) -> str:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.runs.append((due.name, now))
        return "counted"

    @property
    def names(self) -> list[str]:
        return sorted(name for name, _ in self.runs)


async def add(
    engine: AsyncEngine,
    name: str,
    cron: str = EVERY_FIVE,
    *,
    kind: str = RETENTION_PURGE,
    next_run_at: datetime | None = NOW - timedelta(minutes=1),
    enabled: bool = True,
    client_id: int | None = None,
) -> int:
    async with factory_of(engine)() as session, session.begin():
        row = Schedule(
            name=name,
            kind=kind,
            cron=cron,
            enabled=enabled,
            client_id=client_id,
            next_run_at=next_run_at,
            config={},
        )
        session.add(row)
        await session.flush()
        return row.id


async def row_of(engine: AsyncEngine, schedule_id: int) -> Schedule:
    async with factory_of(engine)() as session:
        row = await session.get(Schedule, schedule_id)
    assert row is not None
    return row


# --- check 1: each due schedule runs exactly once ------------------------------------


async def test_a_due_schedule_runs_once_and_is_moved_forward(
    db_engine: AsyncEngine,
) -> None:
    schedule_id = await add(db_engine, "every-five")
    counter = Counter()
    jobs: dict[str, Job] = {RETENTION_PURGE: counter}
    factory = factory_of(db_engine)
    assert await run_due(factory, jobs, NOW) == {"every-five": "counted"}
    row = await row_of(db_engine, schedule_id)
    assert row.last_run_at == NOW
    assert row.next_run_at == next_run_for(EVERY_FIVE, NOW)
    assert row.next_run_at == NOW + timedelta(minutes=5)
    # Looking again at the same moment, or a moment before the next time, runs nothing.
    assert await run_due(factory, jobs, NOW) == {}
    assert await run_due(factory, jobs, NOW + timedelta(minutes=4, seconds=59)) == {}
    assert len(counter.runs) == 1
    # At the next time it runs once more.
    assert await run_due(factory, jobs, NOW + timedelta(minutes=5)) == {
        "every-five": "counted"
    }
    assert len(counter.runs) == 2


async def test_a_schedule_missed_for_hours_runs_once_not_once_per_missed_time(
    db_engine: AsyncEngine,
) -> None:
    schedule_id = await add(db_engine, "every-five")
    counter = Counter()
    jobs: dict[str, Job] = {RETENTION_PURGE: counter}
    later = NOW + timedelta(hours=3)
    await run_due(factory_of(db_engine), jobs, later)
    await run_due(factory_of(db_engine), jobs, later)
    assert len(counter.runs) == 1
    assert (await row_of(db_engine, schedule_id)).next_run_at == later + timedelta(
        minutes=5
    )


async def test_a_schedule_that_is_not_due_or_is_disabled_does_not_run(
    db_engine: AsyncEngine,
) -> None:
    await add(db_engine, "later", next_run_at=NOW + timedelta(minutes=1))
    await add(db_engine, "off", enabled=False)
    await add(db_engine, "waiting", next_run_at=None)
    counter = Counter()
    outcomes = await run_due(factory_of(db_engine), {RETENTION_PURGE: counter}, NOW)
    assert outcomes == {} and counter.runs == []


async def test_two_workers_never_run_the_same_schedule_twice(
    db_engine: AsyncEngine,
) -> None:
    for name in ("a", "b", "c"):
        await add(db_engine, name)
    # Every run takes a while, so the five workers really do overlap.
    counter = Counter(delay=0.3)
    jobs: dict[str, Job] = {RETENTION_PURGE: counter}
    results = await asyncio.gather(
        *(run_due(factory_of(db_engine), jobs, NOW) for _ in range(5))
    )
    assert counter.names == ["a", "b", "c"]
    assert sum(len(result) for result in results) == 3


async def test_a_one_time_schedule_runs_once_and_switches_itself_off(
    db_engine: AsyncEngine,
) -> None:
    schedule_id = await add(db_engine, "once", "@once", next_run_at=NOW)
    counter = Counter()
    jobs: dict[str, Job] = {RETENTION_PURGE: counter}
    await run_due(factory_of(db_engine), jobs, NOW)
    await run_due(factory_of(db_engine), jobs, NOW + timedelta(days=1))
    assert len(counter.runs) == 1
    row = await row_of(db_engine, schedule_id)
    assert row.enabled is False and row.next_run_at is None and row.last_run_at == NOW


async def test_a_new_schedule_gets_its_first_time_and_does_not_run_at_once(
    db_engine: AsyncEngine,
) -> None:
    schedule_id = await add(db_engine, "fresh", next_run_at=None)
    factory = factory_of(db_engine)
    assert await start_unscheduled(factory, NOW) == 1
    assert (await row_of(db_engine, schedule_id)).next_run_at == NOW + timedelta(
        minutes=5
    )
    counter = Counter()
    assert await run_due(factory, {RETENTION_PURGE: counter}, NOW) == {}
    assert await start_unscheduled(factory, NOW) == 0


async def test_a_failing_job_is_audited_and_does_not_stop_the_others(
    db_engine: AsyncEngine,
) -> None:
    await add(db_engine, "boom", kind=DNS_CHECK, client_id=None)
    await add(db_engine, "fine")
    await add(db_engine, "mystery", kind="mystery")
    counter = Counter()

    async def boom(due: DueSchedule, now: datetime) -> str:
        raise RuntimeError("the secret detail of the failure")

    baseline = await audit_baseline(db_engine)
    outcomes = await run_due(
        factory_of(db_engine), {RETENTION_PURGE: counter, DNS_CHECK: boom}, NOW
    )
    assert outcomes == {
        "boom": "failed: RuntimeError",
        "fine": "counted",
        "mystery": "failed: unknown kind",
    }
    events = await audit_since(db_engine, baseline)
    failed = [event for event in events if event.action == "schedule.failed"]
    assert sorted(event.detail["reason"] for event in failed) == [
        "RuntimeError",
        "unknown kind",
    ]
    assert "secret detail" not in str(failed)


async def test_a_schedule_with_an_unreadable_expression_is_switched_off_and_audited(
    db_engine: AsyncEngine,
) -> None:
    schedule_id = await add(db_engine, "broken", "not a cron expression")
    counter = Counter()
    baseline = await audit_baseline(db_engine)
    assert await run_due(factory_of(db_engine), {RETENTION_PURGE: counter}, NOW) == {}
    assert counter.runs == []
    assert (await row_of(db_engine, schedule_id)).enabled is False
    actions = [event.action for event in await audit_since(db_engine, baseline)]
    assert actions == ["schedule.disabled"]


async def test_the_default_schedules_are_created_once_and_never_overwritten(
    db_engine: AsyncEngine,
) -> None:
    factory = factory_of(db_engine)
    await ensure_default_schedules(factory, NOW)
    async with factory() as session:
        names = set((await session.execute(select(Schedule.name))).scalars())
    assert names == {name for name, _, _ in DEFAULT_SCHEDULES}
    async with factory() as session, session.begin():
        row = (
            await session.execute(
                select(Schedule).where(Schedule.name == "retention-purge")
            )
        ).scalar_one()
        row.cron = "0 5 * * *"
        row.enabled = False
    await ensure_default_schedules(factory, NOW)
    async with factory() as session:
        rows = list((await session.execute(select(Schedule))).scalars())
    assert len(rows) == len(DEFAULT_SCHEDULES)
    purge = next(row for row in rows if row.name == "retention-purge")
    assert purge.cron == "0 5 * * *" and purge.enabled is False


# --- the worker loop -------------------------------------------------------------------


async def run_for(
    settings: Settings, engine: AsyncEngine, clock: FakeClock, seconds: float
) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(settings, stop, interval=0.05, engine=engine, clock=clock)
    )
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, timeout=10)


async def test_the_worker_reports_a_heartbeat_creates_the_defaults_and_runs_them(
    ui_settings: Settings, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    await run_for(ui_settings, db_engine, clock, 0.6)
    async with factory_of(db_engine)() as session:
        status = await read_status(session, clock())
        heartbeat = (await session.execute(select(WorkerHeartbeat))).scalar_one()
        names = set((await session.execute(select(Schedule.name))).scalars())
    assert status.state == RUNNING and status.workers == 1
    assert heartbeat.detail["leader"] is True
    assert names == {name for name, _, _ in DEFAULT_SCHEDULES}
    # The purge is due at 03:30 UTC; the fake clock is moved past it.
    clock.now = datetime(2026, 10, 18, 3, 31, tzinfo=clock.now.tzinfo)
    await run_for(ui_settings, db_engine, clock, 0.6)
    async with factory_of(db_engine)() as session:
        purge = (
            await session.execute(
                select(Schedule).where(Schedule.name == "retention-purge")
            )
        ).scalar_one()
        reminders = (
            await session.execute(
                select(Schedule).where(Schedule.name == "expiry-reminders")
            )
        ).scalar_one()
    assert purge.last_run_at == clock()
    assert reminders.last_run_at is None


async def test_the_heartbeat_goes_stale_after_ninety_seconds(
    db_engine: AsyncEngine,
) -> None:
    factory = factory_of(db_engine)
    async with factory() as session:
        assert (await read_status(session, NOW)).state == NEVER
    await beat(factory, "worker-1", NOW, {"leader": True})
    async with factory() as session:
        assert (await read_status(session, NOW + STALE_AFTER)).state == RUNNING
        after = await read_status(session, NOW + STALE_AFTER + timedelta(seconds=1))
    assert after.state == STALE and after.stale
    assert after.age_seconds == pytest.approx(STALE_AFTER.total_seconds() + 1)


# --- check 4: stopping the worker raises the banner within 3 minutes ----------------------


async def test_stopping_the_worker_raises_the_banner_within_three_minutes(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    await sign_in(ui_browser, db_engine)
    factory = factory_of(db_engine)
    # No worker has ever reported: the system page says so, the pages stay quiet.
    assert BANNER not in (await ui_browser.get("/clients")).text
    await beat(factory, "worker-1", clock(), {"leader": True})
    assert BANNER not in (await ui_browser.get("/clients")).text
    # The worker stops. A minute later the pages are still quiet.
    clock.advance(60)
    assert BANNER not in (await ui_browser.get("/clients")).text
    # Two minutes after its last beat the banner is there, on every page.
    clock.advance(60)
    for path in ("/clients", "/", "/settings", "/system"):
        page = await ui_browser.get(path)
        assert page.status_code == 200, path
        assert BANNER in page.text, path
        assert "has not reported for more than 2 minutes" in page.text, path
    clock.advance(60)
    third = await ui_browser.get("/clients")
    assert "has not reported for more than 3 minutes" in third.text
    # The worker is back: the banner is gone.
    await beat(factory, "worker-1", clock(), {"leader": True})
    assert BANNER not in (await ui_browser.get("/clients")).text


async def test_the_system_page_shows_the_worker_and_the_schedules(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    await sign_in(ui_browser, db_engine)
    await add(db_engine, "nightly-purge")
    page = await ui_browser.get("/system")
    assert page.status_code == 200
    assert "No worker has reported yet" in page.text
    assert "nightly-purge" in page.text
    await beat(factory_of(db_engine), "worker-1", clock(), {"leader": True})
    assert "Worker running" in (await ui_browser.get("/system")).text
    clock.advance(STALE_AFTER.total_seconds() + 1)
    assert "Worker not reporting" in (await ui_browser.get("/system")).text


# --- the schedules API ---------------------------------------------------------------------


async def start(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> tuple[dict[str, str], int]:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    created = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Schedule Client Ltd"}
    )
    return token, created.json()["id"]


async def test_schedules_are_created_listed_and_deleted_through_the_api(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token, client_id = await start(client, db_engine)
    baseline = await audit_baseline(db_engine)
    body = {
        "kind": "dns-check",
        "cron": "0 4 * * 1",
        "client_id": client_id,
        "domains": ["client.example"],
        "selectors": ["selector1"],
    }
    created = await client.post("/api/v1/schedules", headers=token, json=body)
    assert created.status_code == 201
    schedule_id = created.json()["id"]
    assert created.json()["next_run_at"].endswith("+00:00")
    listing = await client.get("/api/v1/schedules", headers=token)
    entry = listing.json()["schedules"][0]
    assert entry["id"] == schedule_id and entry["kind"] == "dns-check"
    assert entry["client"] == "Schedule Client Ltd" and entry["enabled"] is True
    async with factory_of(db_engine)() as session:
        stored = await session.get(Schedule, schedule_id)
    assert stored is not None and stored.config["domains"] == ["client.example"]
    duplicate = await client.post("/api/v1/schedules", headers=token, json=body)
    assert duplicate.status_code == 409
    deleted = await client.delete(f"/api/v1/schedules/{schedule_id}", headers=token)
    assert deleted.status_code == 200
    gone = await client.delete(f"/api/v1/schedules/{schedule_id}", headers=token)
    assert gone.status_code == 404
    actions = [event.action for event in await audit_since(db_engine, baseline)]
    assert actions.count("schedule.created") == 1
    assert actions.count("schedule.deleted") == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"cron": "61 * * * *"},
        {"cron": "every day"},
        {"kind": "mystery"},
        {"client_id": None},
        {"kind": "expiry-reminder", "domains": []},
        {"domains": ["not a domain!"]},
        {"name": "bad\x00name"},
    ],
)
async def test_a_schedule_that_cannot_be_used_is_refused(
    client: httpx.AsyncClient, db_engine: AsyncEngine, changes: dict[str, object]
) -> None:
    token, client_id = await start(client, db_engine)
    body: dict[str, object] = {
        "kind": "dns-check",
        "cron": "0 4 * * 1",
        "client_id": client_id,
        "domains": ["client.example"],
    }
    body.update(changes)
    refused = await client.post("/api/v1/schedules", headers=token, json=body)
    assert refused.status_code == 422, refused.text
    async with factory_of(db_engine)() as session:
        assert list((await session.execute(select(Schedule))).scalars()) == []


async def test_a_schedule_for_the_whole_installation_has_no_client(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token, client_id = await start(client, db_engine)
    with_client = {"kind": "retention-purge", "cron": "@daily", "client_id": client_id}
    refused = await client.post("/api/v1/schedules", headers=token, json=with_client)
    assert refused.status_code == 422
    plain = {"kind": "retention-purge", "cron": "@daily"}
    accepted = await client.post("/api/v1/schedules", headers=token, json=plain)
    assert accepted.status_code == 201


async def test_a_snapshot_request_is_queued_once_and_run_by_the_worker_job(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token, client_id = await start(client, db_engine)
    path = f"/api/v1/clients/{client_id}/snapshot-requests"
    first = await client.post(path, headers=token)
    assert first.status_code == 202 and first.json()["queued"] is True
    again = await client.post(path, headers=token)
    assert again.status_code == 202
    assert again.json() == {"id": first.json()["id"], "queued": False}
    missing = await client.post(
        "/api/v1/clients/999999/snapshot-requests", headers=token
    )
    assert missing.status_code == 404
    unauthorised = await client.post(path, headers={"Authorization": "Bearer nope"})
    assert unauthorised.status_code == 401


async def test_the_system_endpoint_reports_the_worker(
    client: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    never = await client.get("/api/v1/system", headers=token)
    assert never.status_code == 200 and never.json()["worker"]["state"] == "never"
    await beat(factory_of(db_engine), "worker-1", clock(), {"leader": True})
    running = await client.get("/api/v1/system", headers=token)
    assert running.json()["worker"]["state"] == "running"
    assert running.json()["stale_after_seconds"] == 90
    assert (await client.get("/api/v1/system")).status_code == 401
