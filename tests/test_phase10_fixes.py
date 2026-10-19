"""Fixes after the review of phase 10: cron dates, heartbeat URL, busy worker, renewal.

These tests need PostgreSQL (DATABASE_URL), like the other worker tests. Time is a
fake clock; the jobs and the mail relay are fakes. Nothing here reaches the network.
"""

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.checks.library import load_library
from app.clock import Clock
from app.evidence.assurance import Assurance
from app.evidence.service import EvidenceContext, NewEvidence, add_revision
from app.main import create_app
from app.models import ReminderSent, Schedule
from app.preferences import set_reminder_recipient
from app.settings import Settings
from app.worker import run_worker
from app.worker.cron import CronError, validate_cron
from app.worker.heartbeat import RUNNING, STALE_AFTER, read_status
from app.worker.jobs import JobContext, build_jobs
from app.worker.ping import Pinger, _get, valid_heartbeat_url
from app.worker.scheduler import EXPIRY_REMINDER, RETENTION_PURGE, DueSchedule, Job
from dns_helpers import StaticResolver
from helpers import NOW, FakeClock, create_test_client, issue_token, upload
from ui_helpers import sign_in

BANNER = 'id="worker-banner"'
NEVER_MATCHING = [
    "0 0 31 2 *",
    "0 0 31 4 *",
    "0 0 30 2 *",
    "59 23 31 6,9,11 *",
]
BAD_HEARTBEAT_URLS = [
    "http://127.0.0.1:abc/x",
    "http://127.0.0.1:99999999/x",
    "http://127.0.0.1/a b",
    "http://127.0.0.1/a" + chr(1) + "b",
    "http://127.0.0.1/a" + chr(10) + "b",
]


def factory_of(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# --- B1: a cron that never meets a real date is refused, not a 500 ---


@pytest.mark.parametrize("cron", NEVER_MATCHING)
def test_a_cron_that_never_meets_a_real_date_is_not_valid(cron: str) -> None:
    with pytest.raises(CronError, match="never matches"):
        validate_cron(cron)


def test_the_leap_day_and_the_once_macro_stay_valid() -> None:
    assert validate_cron("0 0 29 2 *") == "0 0 29 2 *"
    assert validate_cron("@once") == "@once"


@pytest.mark.parametrize("cron", NEVER_MATCHING)
async def test_a_schedule_with_a_cron_that_never_matches_is_422_not_500(
    client: httpx.AsyncClient, db_engine: AsyncEngine, cron: str
) -> None:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    body = {"kind": "retention-purge", "cron": cron}
    refused = await client.post("/api/v1/schedules", headers=token, json=body)
    assert refused.status_code == 422, refused.text
    async with factory_of(db_engine)() as session:
        assert list((await session.execute(select(Schedule))).scalars()) == []


# --- B2: a malformed HEARTBEAT_URL never stops the worker ---


@pytest.mark.parametrize("url", BAD_HEARTBEAT_URLS)
async def test_a_malformed_heartbeat_url_is_refused_and_does_not_raise(
    url: str,
) -> None:
    assert valid_heartbeat_url(url) is False
    assert await Pinger(url).ping_if_due() is False


@pytest.mark.parametrize("url", BAD_HEARTBEAT_URLS)
def test_the_request_survives_an_address_that_urllib_will_not_open(url: str) -> None:
    # Whatever gets past the check must still end as False, never as an exception.
    assert _get(url) is False


def test_a_normal_heartbeat_address_is_still_accepted() -> None:
    assert valid_heartbeat_url("https://monitor.example/ping/abc123?x=1")
    assert valid_heartbeat_url("http://127.0.0.1:8080/ping")
    assert not valid_heartbeat_url("ftp://monitor.example/x")


# --- D1: the heartbeat does not go stale while a long job runs ---


async def test_the_heartbeat_stays_fresh_while_a_job_outlasts_the_stale_limit(
    ui_settings: Settings,
    db_engine: AsyncEngine,
    clock: FakeClock,
    ui_browser: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(due: DueSchedule, now: datetime) -> str:
        started.set()
        await release.wait()
        return "finished"

    def only_slow(context: JobContext) -> dict[str, Job]:
        return {RETENTION_PURGE: slow}

    monkeypatch.setattr("app.worker.build_jobs", only_slow)
    async with factory_of(db_engine)() as session, session.begin():
        session.add(
            Schedule(
                name="long-purge",
                kind=RETENTION_PURGE,
                cron="*/5 * * * *",
                enabled=True,
                next_run_at=clock() - timedelta(minutes=1),
                config={},
            )
        )
    await sign_in(ui_browser, db_engine)
    settings_all = replace(ui_settings, role="all")
    web_all = create_app(settings_all, engine=db_engine, clock=clock)
    stop = asyncio.Event()
    worker = asyncio.create_task(
        run_worker(ui_settings, stop, interval=0.05, engine=db_engine, clock=clock)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        # The job is held for three times the stale limit on the fake clock.
        for _ in range(3):
            clock.advance(STALE_AFTER.total_seconds())
            await asyncio.sleep(0.4)
        async with factory_of(db_engine)() as session:
            status = await read_status(session, clock())
        assert status.state == RUNNING, status
        assert status.age_seconds is not None
        assert status.age_seconds <= STALE_AFTER.total_seconds()
        assert BANNER not in (await ui_browser.get("/clients")).text
        transport = httpx.ASGITransport(app=web_all)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as p:
            assert (await p.get("/readyz")).status_code == 200
    finally:
        release.set()
        stop.set()
        await asyncio.wait_for(worker, timeout=10)


# --- D2: a renewed item is reminded again in the next cycle ---


class Mailbox:
    """A mailer that keeps the messages."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, settings: Settings, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


def make_jobs(
    settings: Settings,
    ctx: EvidenceContext,
    engine: AsyncEngine,
    mailer: Mailbox,
    clock: Clock | None = None,
) -> dict[str, Job]:
    relay = {
        "smtp_host": "127.0.0.1",
        "smtp_port": 587,
        "smtp_from": "rv@msp.example",
    }
    context = JobContext(
        session_factory=factory_of(engine),
        settings=replace(settings, **relay),
        evidence=ctx,
        library=load_library(),
        resolver=StaticResolver(),
        mailer=mailer,
        clock=clock,
    )
    return build_jobs(context)


async def remind(jobs: dict[str, Job], now: datetime) -> str:
    due = DueSchedule(1, "expiry-reminders", EXPIRY_REMINDER, None, {})
    return await jobs[EXPIRY_REMINDER](due, now)


async def reminder_rows(engine: AsyncEngine) -> set[tuple[int, int]]:
    async with factory_of(engine)() as session:
        found = await session.execute(
            select(ReminderSent.item_id, ReminderSent.threshold_days)
        )
        return {(item_id, days) for item_id, days in found.all()}


async def test_a_renewed_attestation_is_reminded_again_the_next_year(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, "Renewal Test Ltd")
    first = NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=NOW - timedelta(days=1),
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, 16),
        note="Staff training was completed",
    )
    stored = await upload(db_engine, ui_ctx, client_id, first, NOW)
    mailbox = Mailbox()
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    async with factory_of(db_engine)() as session, session.begin():
        await set_reminder_recipient(
            session, "owner@msp.example", user_id=None, now=NOW
        )

    async def cycle(expires_at: datetime) -> None:
        early = expires_at - timedelta(days=31)
        assert await remind(jobs, early) == "nothing is due"
        for days in (29, 6, 0):
            moment = expires_at - timedelta(days=days)
            assert await remind(jobs, moment) == "sent 1 reminders in one message"
            assert await remind(jobs, moment) == "nothing is due"

    # First cycle: reminders at 30, 7 and 0 days.
    await cycle(stored.expires_at)
    assert len(mailbox.sent) == 3
    item = stored.item_id
    assert await reminder_rows(db_engine) == {(item, 30), (item, 7), (item, 0)}

    # The attestation is renewed a day after it went stale: same item, new expiry.
    renewed_at = stored.expires_at + timedelta(days=1)
    renewal = NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=renewed_at,
        reviewer="Sam Reviewer",
        reviewed_on=renewed_at.date(),
        note="Staff training was completed again",
    )
    async with factory_of(db_engine)() as session, session.begin():
        revised = await add_revision(
            session, ui_ctx, client_id, item, renewal, renewed_at
        )
    assert revised.item_id == item and revised.expires_at > stored.expires_at
    assert await remind(jobs, renewed_at) == "nothing is due"
    assert await reminder_rows(db_engine) == set()

    # Second cycle: the same three reminders, for the new expiry.
    await cycle(revised.expires_at)
    assert len(mailbox.sent) == 6
    assert await reminder_rows(db_engine) == {(item, 30), (item, 7), (item, 0)}


# --- phase 11: a correction is not a renewal, and a claim has the time it was made ---


async def attested(
    ctx: EvidenceContext, engine: AsyncEngine, name: str
) -> tuple[int, int, datetime]:
    """An attestation: the client id, the item id and the moment it goes stale."""
    client_id = await create_test_client(engine, ctx, name)
    first = NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=NOW - timedelta(days=1),
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, 16),
        note="Staff training was completed",
    )
    stored = await upload(engine, ctx, client_id, first, NOW)
    async with factory_of(engine)() as session, session.begin():
        await set_reminder_recipient(
            session, "owner@msp.example", user_id=None, now=NOW
        )
    return client_id, stored.item_id, stored.expires_at


async def test_a_correction_with_the_same_expiry_is_not_reminded_again(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    client_id, item, expires_at = await attested(ui_ctx, db_engine, "Correction Ltd")
    mailbox = Mailbox()
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    moment = expires_at - timedelta(days=6)
    assert await remind(jobs, moment) == "sent 1 reminders in one message"
    assert await reminder_rows(db_engine) == {(item, 30), (item, 7)}

    # A typing mistake in the note is corrected an hour after the reminder went out
    # (a correction made at the same moment would not tell the old rule from the new
    # one); the expiry stays as it was.
    later = moment + timedelta(hours=1)
    correction = NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=NOW - timedelta(days=1),
        expires_at=expires_at,
        reviewer="Sam Reviewer",
        reviewed_on=date(2026, 10, 16),
        note="Staff training was completed (date corrected)",
    )
    async with factory_of(db_engine)() as session, session.begin():
        revised = await add_revision(
            session, ui_ctx, client_id, item, correction, later
        )
    assert revised.expires_at == expires_at
    assert await remind(jobs, later) == "nothing is due"
    assert await reminder_rows(db_engine) == {(item, 30), (item, 7)}
    assert len(mailbox.sent) == 1

    # The threshold that has not been sent yet still goes out when it is reached.
    assert await remind(jobs, expires_at) == "sent 1 reminders in one message"
    assert await reminder_rows(db_engine) == {(item, 30), (item, 7), (item, 0)}
    assert len(mailbox.sent) == 2


async def test_a_threshold_crossed_a_day_early_is_not_dropped_as_old(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    _, item, expires_at = await attested(ui_ctx, db_engine, "Early Ltd")
    mailbox = Mailbox()
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    # Days are rounded down: with 7.9 days left, 7 days is already crossed.
    moment = expires_at - timedelta(days=7, hours=22)
    assert await remind(jobs, moment) == "sent 1 reminders in one message"
    assert (item, 7) in await reminder_rows(db_engine)
    assert await remind(jobs, moment + timedelta(days=1)) == "nothing is due"
    assert len(mailbox.sent) == 1


async def test_the_reminder_rows_carry_the_time_of_the_claim(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    _, _, expires_at = await attested(ui_ctx, db_engine, "Claim Time Ltd")
    tick = expires_at - timedelta(days=6)
    claimed = tick + timedelta(minutes=45)
    jobs = make_jobs(settings, ui_ctx, db_engine, Mailbox(), clock=lambda: claimed)
    assert await remind(jobs, tick) == "sent 1 reminders in one message"
    async with factory_of(db_engine)() as session:
        stamps = (await session.execute(select(ReminderSent.sent_at))).scalars()
        assert set(stamps) == {claimed}
