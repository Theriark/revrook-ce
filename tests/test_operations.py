"""Reminders, mail, purge, export, deletion, metrics, outside heartbeat (phase 10).

These tests need PostgreSQL (DATABASE_URL). The mail relay is a fake one on 127.0.0.1
with a throwaway certificate, the heartbeat target is a local web server, the
resolver is a fake and the data is synthetic: nothing reaches the network.
"""

import csv
import functools
import http.server
import io
import ipaddress
import re
import socket
import ssl
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import __version__
from app.auth import issue_api_token
from app.checks.library import load_library
from app.evidence.chain import verify_chain
from app.evidence.service import EvidenceContext
from app.main import create_app
from app.models import (
    AppUser,
    Client,
    EvidenceItem,
    EvidenceRevision,
    ExceptionRecord,
    ReminderSent,
    ReportExport,
    Schedule,
    Snapshot,
)
from app.preferences import set_reminder_recipient
from app.settings import Settings
from app.worker.heartbeat import beat
from app.worker.jobs import JobContext, build_jobs
from app.worker.mail import MailError, mail_configured, send_mail
from app.worker.ping import Pinger
from app.worker.purge import PurgeResult, run_purge
from app.worker.scheduler import EXPIRY_REMINDER, DueSchedule, Job
from dns_helpers import StaticResolver
from helpers import (
    NOW,
    FakeClock,
    audit_baseline,
    audit_since,
    create_admin,
    create_test_client,
    export_evidence,
    get_csrf,
    issue_token,
    login,
    make_context,
    upload,
    users_csv,
)
from ui_helpers import NAME, seed_client, sign_in

RECIPIENT = "owner@msp.example"
CLIENT_NAME = "Alder Finch Ltd"


def factory_of(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def count(engine: AsyncEngine, model: type) -> int:
    async with factory_of(engine)() as session:
        query = select(func.count()).select_from(model)
        return int((await session.execute(query)).scalar_one())


def later(days: float) -> datetime:
    return NOW + timedelta(days=days)


# --- the expiry reminders ---


class Mailbox:
    """A mailer that keeps the messages, or fails when told to."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    def __call__(self, settings: Settings, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise MailError("the mail could not be sent: ConnectionRefusedError")
        self.sent.append((to, subject, body))


def make_jobs(
    settings: Settings,
    ctx: EvidenceContext,
    engine: AsyncEngine,
    mailer: Mailbox | functools.partial[None],
    *,
    relay: bool = True,
    resolver: StaticResolver | None = None,
    port: int = 587,
) -> dict[str, Job]:
    changes = (
        {"smtp_host": "127.0.0.1", "smtp_port": port, "smtp_from": "rv@msp.example"}
        if relay
        else {}
    )
    context = JobContext(
        session_factory=factory_of(engine),
        settings=replace(settings, **changes),
        evidence=ctx,
        library=load_library(),
        resolver=resolver or StaticResolver(),
        mailer=mailer,
    )
    return build_jobs(context)


async def remind(jobs: dict[str, Job], now: datetime) -> str:
    due = DueSchedule(1, "expiry-reminders", EXPIRY_REMINDER, None, {})
    return await jobs[EXPIRY_REMINDER](due, now)


async def set_recipient(engine: AsyncEngine, address: str = RECIPIENT) -> None:
    async with factory_of(engine)() as session, session.begin():
        await set_reminder_recipient(session, address, user_id=None, now=NOW)


async def reminder_rows(engine: AsyncEngine) -> set[tuple[int, int]]:
    async with factory_of(engine)() as session:
        found = await session.execute(
            select(ReminderSent.item_id, ReminderSent.threshold_days)
        )
        return {(item_id, days) for item_id, days in found.all()}


async def test_a_reminder_is_sent_once_per_threshold_crossing(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, CLIENT_NAME)
    stored = await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    mailbox = Mailbox()
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    await set_recipient(db_engine)
    # The export was captured two days ago, so it is stale 33 days from NOW. One
    # that lives 35 days has no 30 day reminder, only 7 days and the day itself.
    assert await remind(jobs, later(20)) == "nothing is due"
    assert await remind(jobs, later(26)) == "sent 1 reminders in one message"
    assert await remind(jobs, later(26)) == "nothing is due"
    assert await remind(jobs, later(30)) == "nothing is due"
    assert await remind(jobs, later(33)) == "sent 1 reminders in one message"
    assert await remind(jobs, later(33)) == "nothing is due"
    assert await remind(jobs, later(36)) == "nothing is due"
    assert len(mailbox.sent) == 2
    assert await reminder_rows(db_engine) == {(stored.item_id, 7), (stored.item_id, 0)}
    to, subject, body = mailbox.sent[0]
    assert to == RECIPIENT and subject.startswith("revrook:")
    assert CLIENT_NAME in body and "reference-csv" in body
    assert "goes stale on" in body
    assert "goes stale today" in mailbox.sent[1][2]


async def test_an_item_first_seen_late_sends_one_line_with_both_thresholds(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, CLIENT_NAME)
    stored = await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    mailbox = Mailbox()
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    await set_recipient(db_engine)
    assert await remind(jobs, later(33)) == "sent 1 reminders in one message"
    assert len(mailbox.sent) == 1
    assert mailbox.sent[0][2].count(CLIENT_NAME) == 1
    assert await reminder_rows(db_engine) == {(stored.item_id, 7), (stored.item_id, 0)}
    assert await remind(jobs, later(34)) == "nothing is due"
    assert len(mailbox.sent) == 1


async def test_only_the_newest_item_of_a_source_is_reminded(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, CLIENT_NAME)
    await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    refreshed = export_evidence(
        data=users_csv((("dora.synthetic@example.test", True),)),
        captured_at=later(9),
    )
    await upload(db_engine, ui_ctx, client_id, refreshed, later(10))
    mailbox = Mailbox()
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    await set_recipient(db_engine)
    # The first export would be due now; the refreshed one is not, and it counts.
    assert await remind(jobs, later(30)) == "nothing is due"
    assert mailbox.sent == []


async def test_a_message_that_cannot_be_sent_is_tried_again_at_the_next_run(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, CLIENT_NAME)
    await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    mailbox = Mailbox()
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    await set_recipient(db_engine)
    baseline = await audit_baseline(db_engine)
    mailbox.fail = True
    with pytest.raises(MailError):
        await remind(jobs, later(26))
    assert await reminder_rows(db_engine) == set()
    assert mailbox.sent == []
    mailbox.fail = False
    assert await remind(jobs, later(26)) == "sent 1 reminders in one message"
    assert len(mailbox.sent) == 1
    events = await audit_since(db_engine, baseline)
    sent = [event for event in events if "reminder" in event.action]
    assert [event.action for event in sent] == ["reminder.sent"]
    assert sent[0].detail == {"items": 1, "clients": 1, "thresholds": [7]}


async def test_no_message_is_sent_without_an_address_or_a_relay(
    settings: Settings, ui_ctx: EvidenceContext, db_engine: AsyncEngine
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, CLIENT_NAME)
    await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    mailbox = Mailbox()
    skipped = "skipped: no reminder address or no mail relay is set"
    jobs = make_jobs(settings, ui_ctx, db_engine, mailbox)
    assert await remind(jobs, later(26)) == skipped
    await set_recipient(db_engine)
    without_relay = make_jobs(settings, ui_ctx, db_engine, mailbox, relay=False)
    assert await remind(without_relay, later(26)) == skipped
    assert mailbox.sent == [] and await reminder_rows(db_engine) == set()
    # Once both are there, the reminder that was waiting goes out.
    assert await remind(jobs, later(26)) == "sent 1 reminders in one message"


@pytest.mark.parametrize(
    "address", ["", "a b@msp.example", "a@b", "a@msp.example,b@msp.example", "<a@b.c>"]
)
async def test_a_reminder_address_must_be_one_plain_address(
    db_engine: AsyncEngine, address: str
) -> None:
    async with factory_of(db_engine)() as session, session.begin():
        if address == "":
            cleared = await set_reminder_recipient(session, "", user_id=None, now=NOW)
            assert cleared is None
            return
        with pytest.raises(ValueError, match="one plain email address"):
            await set_reminder_recipient(session, address, user_id=None, now=NOW)


# --- mail: STARTTLS, always ---


class LineReader:
    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.buffer = b""

    def line(self) -> bytes | None:
        while b"\r\n" not in self.buffer:
            chunk = self.connection.recv(4096)
            if not chunk:
                return None
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\r\n")
        return line


class FakeSmtp:
    """A relay on 127.0.0.1 that offers STARTTLS (or not) and keeps what it is sent."""

    def __init__(self, context: ssl.SSLContext | None) -> None:
        self.context = context
        self.commands: list[str] = []
        self.messages: list[str] = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.listener.settimeout(0.2)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.listener.getsockname()[1])

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=5)
        self.listener.close()

    def serve(self) -> None:
        while not self.stopped.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            connection.settimeout(5)
            try:
                self.session(connection)
            except OSError:
                self.commands.append("(connection failed)")
            finally:
                connection.close()

    def session(self, connection: socket.socket) -> None:
        reader = LineReader(connection)
        encrypted = False
        connection.sendall(b"220 fake.test ESMTP\r\n")
        while (raw := reader.line()) is not None:
            verb = raw.decode("ascii", "replace").split(" ", 1)[0].upper()
            self.commands.append(verb)
            if verb == "EHLO":
                lines = ["250-fake.test"]
                if self.context is not None and not encrypted:
                    lines.append("250-STARTTLS")
                lines.append("250 8BITMIME")
                connection.sendall(("\r\n".join(lines) + "\r\n").encode())
            elif verb == "STARTTLS" and self.context is not None:
                connection.sendall(b"220 ready\r\n")
                connection = self.context.wrap_socket(connection, server_side=True)
                reader = LineReader(connection)
                encrypted = True
            elif verb == "DATA":
                connection.sendall(b"354 go on\r\n")
                body: list[str] = []
                while (part := reader.line()) is not None and part != b".":
                    body.append(part.decode("utf-8", "replace"))
                self.messages.append("\n".join(body))
                connection.sendall(b"250 queued\r\n")
            elif verb == "QUIT":
                connection.sendall(b"221 bye\r\n")
                return
            else:
                connection.sendall(b"250 ok\r\n")


def make_contexts(directory: Path) -> tuple[ssl.SSLContext, ssl.SSLContext]:
    """The server context of a throwaway certificate, and a client trusting it."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    start = datetime.now(UTC) - timedelta(days=1)
    address = x509.IPAddress(ipaddress.ip_address("127.0.0.1"))
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=3))
        .add_extension(x509.SubjectAlternativeName([address]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    (directory / "cert.pem").write_bytes(certificate_pem)
    (directory / "key.pem").write_bytes(key_pem)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(directory / "cert.pem", directory / "key.pem")
    trusted = ssl.create_default_context(cadata=certificate_pem.decode())
    return server, trusted


@pytest.fixture
def contexts(tmp_path: Path) -> tuple[ssl.SSLContext, ssl.SSLContext]:
    return make_contexts(tmp_path)


@pytest.fixture
def relay(contexts: tuple[ssl.SSLContext, ssl.SSLContext]) -> Iterator[FakeSmtp]:
    fake = FakeSmtp(contexts[0])
    yield fake
    fake.stop()


@pytest.fixture
def plain_relay() -> Iterator[FakeSmtp]:
    fake = FakeSmtp(None)
    yield fake
    fake.stop()


def relay_settings(settings: Settings, port: int, **changes: Any) -> Settings:
    return replace(
        settings,
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_from="revrook@msp.example",
        **changes,
    )


def test_a_message_goes_out_only_after_starttls(
    settings: Settings,
    relay: FakeSmtp,
    contexts: tuple[ssl.SSLContext, ssl.SSLContext],
) -> None:
    send_mail(
        relay_settings(settings, relay.port),
        RECIPIENT,
        "Evidence is about to expire",
        "Client: Alder Finch Ltd\n",
        tls_context=contexts[1],
    )
    assert relay.commands == [
        "EHLO",
        "STARTTLS",
        "EHLO",
        "MAIL",
        "RCPT",
        "DATA",
        "QUIT",
    ]
    assert len(relay.messages) == 1
    assert f"To: {RECIPIENT}" in relay.messages[0]
    assert "From: revrook@msp.example" in relay.messages[0]
    assert "Subject: Evidence is about to expire" in relay.messages[0]
    assert "Alder Finch Ltd" in relay.messages[0]


def test_a_relay_without_starttls_gets_no_message_and_no_password(
    settings: Settings, plain_relay: FakeSmtp
) -> None:
    configured = relay_settings(
        settings, plain_relay.port, smtp_user="relay-user", smtp_password="s3cr3t-pw"
    )
    with pytest.raises(MailError, match="does not offer STARTTLS") as raised:
        send_mail(configured, RECIPIENT, "Subject", "Body\n")
    assert "s3cr3t-pw" not in str(raised.value)
    assert "MAIL" not in plain_relay.commands
    assert "AUTH" not in plain_relay.commands
    assert plain_relay.messages == []


def test_a_certificate_that_is_not_trusted_stops_the_message(
    settings: Settings, relay: FakeSmtp
) -> None:
    # The default context knows only the system certificates, not the throwaway one.
    with pytest.raises(MailError, match="could not be sent: SSLCertVerificationError"):
        send_mail(relay_settings(settings, relay.port), RECIPIENT, "Subject", "Body\n")
    assert "MAIL" not in relay.commands
    assert relay.messages == []


def test_a_relay_that_is_not_there_is_reported_without_its_text(
    settings: Settings,
) -> None:
    with pytest.raises(MailError, match="could not be sent: ConnectionRefusedError"):
        send_mail(relay_settings(settings, 1), RECIPIENT, "Subject", "Body\n")


def test_a_line_break_in_the_subject_is_refused(settings: Settings) -> None:
    with pytest.raises(MailError, match="line break in a header"):
        send_mail(relay_settings(settings, 1), RECIPIENT, "One\nBcc: x@y.z", "Body\n")


def test_mail_needs_a_relay_and_a_sender(settings: Settings) -> None:
    assert not mail_configured(settings)
    assert not mail_configured(replace(settings, smtp_host="smtp.msp.example"))
    assert mail_configured(
        replace(settings, smtp_host="smtp.msp.example", smtp_from="a@msp.example")
    )
    assert mail_configured(
        replace(settings, smtp_host="smtp.msp.example", smtp_user="login")
    )
    with pytest.raises(MailError, match="SMTP_HOST and SMTP_FROM"):
        send_mail(settings, RECIPIENT, "Subject", "Body\n")


async def test_the_reminder_job_sends_through_the_relay_with_starttls(
    settings: Settings,
    ui_ctx: EvidenceContext,
    db_engine: AsyncEngine,
    relay: FakeSmtp,
    contexts: tuple[ssl.SSLContext, ssl.SSLContext],
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, CLIENT_NAME)
    await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    mailer = functools.partial(send_mail, tls_context=contexts[1])
    jobs = make_jobs(settings, ui_ctx, db_engine, mailer, port=relay.port)
    await set_recipient(db_engine)
    assert await remind(jobs, later(26)) == "sent 1 reminders in one message"
    assert await remind(jobs, later(26)) == "nothing is due"
    assert "STARTTLS" in relay.commands
    assert len(relay.messages) == 1 and CLIENT_NAME in relay.messages[0]


# --- the outside heartbeat ---


@pytest.fixture
def monitor() -> Iterator[tuple[str, list[tuple[str, str]], list[int]]]:
    """A local web server: its URL, the requests it saw and the status it answers."""
    seen: list[tuple[str, str]] = []
    status = [200]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append((self.path, self.headers.get("User-Agent", "")))
            self.send_response(status[0])
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/ping/abc123", seen, status
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


async def test_the_heartbeat_is_a_plain_get_at_most_once_per_interval(
    monitor: tuple[str, list[tuple[str, str]], list[int]],
) -> None:
    url, seen, status = monitor
    pinger = Pinger(url)
    assert await pinger.ping_if_due() is True
    assert await pinger.ping_if_due() is None
    assert seen == [("/ping/abc123", "revrook-heartbeat")]
    status[0] = 500
    eager = Pinger(url, interval=0.0)
    assert await eager.ping_if_due() is False
    status[0] = 204
    assert await eager.ping_if_due() is True


async def test_no_heartbeat_is_sent_without_an_address_or_with_a_wrong_one(
    monitor: tuple[str, list[tuple[str, str]], list[int]],
) -> None:
    _, seen, _ = monitor
    assert await Pinger(None).ping_if_due() is None
    assert await Pinger("ftp://monitor.example/x").ping_if_due() is False
    assert await Pinger("not a url").ping_if_due() is False
    assert seen == []


# --- the retention purge ---


def snapshot_row(client_id: int, created_at: datetime) -> Snapshot:
    return Snapshot(
        client_id=client_id,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 9, 30),
        as_of=created_at,
        ruleset_version="1.0.0",
        importer_versions={},
        inputs={},
        created_at=created_at,
    )


def export_row(client_id: int, key: str, exported_at: datetime) -> ReportExport:
    return ReportExport(
        client_id=client_id,
        kind="qbr",
        filename="report.pdf",
        file_sha256="a" * 64,
        size_bytes=10,
        storage_key=key,
        exported_at=exported_at,
    )


async def test_the_purge_removes_only_what_has_expired_and_audits_each_removal(
    ui_settings: Settings, db_engine: AsyncEngine
) -> None:
    files_root = Path(ui_settings.evidence_dir)
    ctx = make_context(ui_settings, files_root, raw_retention_days=30)
    factory = factory_of(db_engine)
    client_id = await create_test_client(db_engine, ctx, CLIENT_NAME)
    # Two raw files: one kept for 30 days from NOW, one from 20 days later.
    old = await upload(db_engine, ctx, client_id, export_evidence(), NOW)
    fresh_data = users_csv((("erin.synthetic@example.test", True),))
    fresh_export = export_evidence(data=fresh_data, captured_at=later(18))
    fresh = await upload(db_engine, ctx, client_id, fresh_export, later(20))
    async with factory() as session:
        found = await session.execute(
            select(EvidenceRevision.item_id, EvidenceRevision.storage_key)
        )
        keys = {item_id: key for item_id, key in found.all()}
    assert keys[old.item_id] is not None and keys[fresh.item_id] is not None
    old_key, fresh_key = str(keys[old.item_id]), str(keys[fresh.item_id])
    # Packs: a snapshot and an export past 25 months and ones from last month.
    old_export_key = ctx.files.put(client_id, b"an old exported report")
    new_export_key = ctx.files.put(client_id, b"a recent exported report")
    long_ago, recently = later(-800), later(-30)
    async with factory() as session, session.begin():
        session.add_all(
            [
                snapshot_row(client_id, long_ago),
                snapshot_row(client_id, recently),
                export_row(client_id, old_export_key, long_ago),
                export_row(client_id, new_export_key, recently),
            ]
        )
        # A request for a snapshot that ran a month ago, and one that ran lately.
        for name, ran in (("request-old", later(-30)), ("request-new", later(30))):
            session.add(
                Schedule(
                    name=name,
                    kind="snapshot-build",
                    cron="@once",
                    enabled=False,
                    client_id=client_id,
                    last_run_at=ran,
                )
            )
    # The folder of a client that no longer exists (a deletion that stopped).
    ctx.files.put(987654321, b"left behind")
    purge_time = later(35)
    baseline = await audit_baseline(db_engine)
    result = await run_purge(factory, ctx.files, purge_time, 25)
    assert result == PurgeResult(
        raw_files=1, snapshots=1, exports=1, leftover_folders=1, finished_requests=1
    )
    # Only the expired rows and files went.
    assert not ctx.files.exists(old_key) and ctx.files.exists(fresh_key)
    assert not ctx.files.exists(old_export_key) and ctx.files.exists(new_export_key)
    assert 987654321 not in ctx.files.client_ids_on_disk()
    assert await count(db_engine, Snapshot) == 1
    assert await count(db_engine, ReportExport) == 1
    assert await count(db_engine, EvidenceItem) == 2
    async with factory() as session:
        names = set((await session.execute(select(Schedule.name))).scalars())
        chain = await verify_chain(session, client_id)
    assert names == {"request-new"}
    assert chain.ok and chain.records >= 3
    # Every removal is an audit event; the run itself is one more.
    actions = sorted(e.action for e in await audit_since(db_engine, baseline))
    assert actions == [
        "evidence.raw_purged",
        "export.purged",
        "files.leftover_removed",
        "retention.run",
        "snapshot.purged",
    ]
    # A second run finds nothing and writes nothing.
    again = await audit_baseline(db_engine)
    assert (await run_purge(factory, ctx.files, purge_time, 25)).total == 0
    assert await audit_since(db_engine, again) == []


async def test_a_purge_of_an_empty_installation_is_quiet(
    ui_settings: Settings, db_engine: AsyncEngine
) -> None:
    ctx = make_context(ui_settings, Path(ui_settings.evidence_dir))
    baseline = await audit_baseline(db_engine)
    result = await run_purge(factory_of(db_engine), ctx.files, NOW, 25)
    assert result.total == 0 and result.summary().startswith("0 raw files")
    assert await audit_since(db_engine, baseline) == []


# --- the data export ---

TABLES = {
    "clients",
    "evidence_items",
    "evidence_revisions",
    "facts",
    "snapshots",
    "control_results",
    "exceptions",
    "report_exports",
    "schedules",
    "audit_events",
    "evidence_log",
}


def read_zip(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.testzip() is None
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def rows_of(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


async def test_the_export_holds_every_table_and_no_personal_identifier(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    user_id = await create_admin(db_engine, "unique.person.name")
    signed_in = await login(ui_browser, username="unique.person.name")
    assert signed_in.status_code == 303
    csrf = await get_csrf(ui_browser, "/clients")
    client_id = await seed_client(db_engine, ui_ctx)
    async with factory_of(db_engine)() as session, session.begin():
        user = await session.get(AppUser, user_id)
        assert user is not None
        token = await issue_api_token(session, user, "tests")
        session.add(
            ExceptionRecord(
                client_id=client_id,
                control_id="PC-ACC-01",
                owner="Pat Quill Owner",
                reason="Accepted by Pat Quill",
                review_date=date(2026, 12, 1),
            )
        )
    baseline = await audit_baseline(db_engine)
    response = await ui_browser.post("/system/export", data={"csrf_token": csrf})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="revrook-export-2026'
    )
    assert response.headers["cache-control"] == "no-store"
    files = read_zip(response.content)
    assert set(files) == {f"{name}.csv" for name in TABLES} | {
        "manifest.csv",
        "README.txt",
    }
    # The manifest counts the rows of each file, and the data is all there.
    manifest = {row["file"]: int(row["rows"]) for row in rows_of(files["manifest.csv"])}
    for name in TABLES:
        assert manifest[f"{name}.csv"] == len(rows_of(files[f"{name}.csv"])), name
    assert [row["name"] for row in rows_of(files["clients.csv"])] == [NAME]
    assert manifest["evidence_items.csv"] == 6 and manifest["exceptions.csv"] == 1
    assert manifest["evidence_log.csv"] >= 6
    # Nothing that names a person: accounts, tokens, hashes, typed names and texts.
    everything = "\n".join(files.values())
    for secret in (
        "unique.person.name",
        token,
        "$argon2",
        "Pat Quill",
        "Accepted by Pat",
        "pseudonym_key",
    ):
        assert secret not in everything, secret
    for header in ("owner", "reason", "uploader", "actor", "username", "notes"):
        assert header not in files["exceptions.csv"].split("\r\n")[0]
        assert header not in files["audit_events.csv"].split("\r\n")[0]
    # The export itself is audited, with counts only.
    events = await audit_since(db_engine, baseline)
    exported = [event for event in events if "export" in event.action]
    assert [event.action for event in exported] == ["data.exported"]
    assert exported[0].detail["files"] == len(TABLES)


async def test_the_export_through_the_api_needs_a_token_and_is_audited(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    assert (await client.get("/api/v1/export")).status_code == 401
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    baseline = await audit_baseline(db_engine)
    response = await client.get("/api/v1/export", headers=token)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    files = read_zip(response.content)
    assert files["README.txt"].startswith("revrook data export")
    assert f"revrook {__version__}" in files["README.txt"]
    actions = [event.action for event in await audit_since(db_engine, baseline)]
    assert actions == ["data.exported"]


async def test_a_page_post_for_the_export_needs_the_csrf_token(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await sign_in(ui_browser, db_engine)
    refused = await ui_browser.post("/system/export")
    assert refused.status_code == 403


async def test_a_name_that_looks_like_a_formula_is_defused_in_the_export(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    made = await client.post(
        "/api/v1/clients", headers=token, json={"name": "=HYPERLINK(1+1)"}
    )
    assert made.status_code == 201
    files = read_zip((await client.get("/api/v1/export", headers=token)).content)
    assert rows_of(files["clients.csv"])[0]["name"] == "'=HYPERLINK(1+1)"


# --- deleting one client ---


async def test_deleting_a_client_from_the_system_page_removes_it_and_is_audited(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    doomed = await seed_client(db_engine, ui_ctx, "Doomed Client Ltd")
    other = await seed_client(db_engine, ui_ctx, "Other Client Ltd")
    ui_ctx.files.put(doomed, b"a kept raw file of the doomed client")
    ui_ctx.files.put(other, b"a kept raw file of the other client")
    path = f"/system/clients/{doomed}/delete"
    baseline = await audit_baseline(db_engine)
    # A confirmation that is not the name changes nothing.
    wrong = await ui_browser.post(path, data={"csrf_token": csrf, "confirm": "Doomed"})
    assert wrong.status_code == 422
    assert await count(db_engine, Client) == 2
    assert ui_ctx.files.count_client_files(doomed) == 1
    # Without the token it is refused too.
    untokened = await ui_browser.post(path, data={"confirm": "Doomed Client Ltd"})
    assert untokened.status_code == 403
    right = await ui_browser.post(
        path, data={"csrf_token": csrf, "confirm": "Doomed Client Ltd"}
    )
    assert right.status_code == 303 and right.headers["location"] == "/system?deleted=1"
    assert await count(db_engine, Client) == 1
    assert ui_ctx.files.count_client_files(doomed) == 0
    assert ui_ctx.files.count_client_files(other) == 1
    page = await ui_browser.get("/system?deleted=1")
    assert "was deleted" in page.text and "Doomed Client Ltd" not in page.text
    events = await audit_since(db_engine, baseline)
    deleted = [event for event in events if "deleted" in event.action]
    assert [event.action for event in deleted] == ["client.deleted"]
    assert deleted[0].target_id == str(doomed)
    assert deleted[0].detail["items"] == 6 and deleted[0].detail["files"] == 1
    async with factory_of(db_engine)() as session:
        survivors = list((await session.execute(select(Client.name))).scalars())
    assert survivors == ["Other Client Ltd"]


# --- Prometheus metrics ---

# The snapshot: a dashboard or an alert breaks when one of these names changes.
METRIC_SNAPSHOT = [
    ("revrook_build_info", "gauge"),
    ("revrook_clients", "gauge"),
    ("revrook_evidence_items", "gauge"),
    ("revrook_snapshots", "gauge"),
    ("revrook_report_exports", "gauge"),
    ("revrook_audit_events_total", "counter"),
    ("revrook_schedules_enabled", "gauge"),
    ("revrook_schedules_overdue", "gauge"),
    ("revrook_worker_up", "gauge"),
    ("revrook_worker_heartbeat_age_seconds", "gauge"),
]
METRIC_NAMES = [name for name, _ in METRIC_SNAPSHOT]
METRIC_LINE = re.compile(r"(revrook_[a-z_]+)(\{[^}]*\})? (-?[0-9]+(?:\.[0-9]+)?|NaN)")
TOKEN = "synthetic-metrics-token-0123456789"


def metrics_app(
    settings: Settings, engine: AsyncEngine, clock: FakeClock, token: str | None
) -> httpx.AsyncClient:
    app = create_app(replace(settings, metrics_token=token), engine=engine, clock=clock)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_metrics_are_off_without_a_token(
    ui_settings: Settings, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    async with metrics_app(ui_settings, db_engine, clock, None) as client:
        assert (await client.get("/metrics")).status_code == 404
        header = {"Authorization": f"Bearer {TOKEN}"}
        assert (await client.get("/metrics", headers=header)).status_code == 404


@pytest.mark.parametrize(
    "header",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}],
)
async def test_metrics_need_the_token(
    ui_settings: Settings,
    db_engine: AsyncEngine,
    clock: FakeClock,
    header: dict[str, str],
) -> None:
    async with metrics_app(ui_settings, db_engine, clock, TOKEN) as client:
        refused = await client.get("/metrics", headers=header)
    assert refused.status_code == 401
    assert refused.headers["www-authenticate"] == "Bearer"
    assert TOKEN not in refused.text


async def test_the_metric_names_and_types_match_the_snapshot(
    ui_settings: Settings, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    async with metrics_app(ui_settings, db_engine, clock, TOKEN) as client:
        response = await client.get(
            "/metrics", headers={"Authorization": f"Bearer {TOKEN}"}
        )
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert content_type == "text/plain; version=0.0.4; charset=utf-8"
    lines = response.text.splitlines()
    helps = [line.split(" ")[2] for line in lines if line.startswith("# HELP ")]
    types = [line.split(" ")[2:] for line in lines if line.startswith("# TYPE ")]
    assert helps == METRIC_NAMES
    assert types == [list(pair) for pair in METRIC_SNAPSHOT]
    samples = [line for line in lines if not line.startswith("#")]
    assert [METRIC_LINE.fullmatch(line) is not None for line in samples] == [True] * 10
    assert [line.split(" ")[0].split("{")[0] for line in samples] == METRIC_NAMES
    assert samples[0] == f'revrook_build_info{{version="{__version__}"}} 1'
    assert response.text.endswith("\n")


async def test_the_metric_values_follow_the_data_and_name_nobody(
    ui_settings: Settings,
    db_engine: AsyncEngine,
    clock: FakeClock,
    ui_ctx: EvidenceContext,
) -> None:
    await seed_client(db_engine, ui_ctx, "Secret Client Name Ltd")
    async with metrics_app(ui_settings, db_engine, clock, TOKEN) as client:
        header = {"Authorization": f"Bearer {TOKEN}"}
        before = (await client.get("/metrics", headers=header)).text
        await beat(factory_of(db_engine), "worker-1", clock(), {"leader": True})
        after = (await client.get("/metrics", headers=header)).text
    assert "revrook_clients 1\n" in before
    assert "revrook_evidence_items 6\n" in before
    assert "revrook_worker_up 0\n" in before
    assert "revrook_worker_heartbeat_age_seconds NaN\n" in before
    assert "revrook_worker_up 1\n" in after
    assert "revrook_worker_heartbeat_age_seconds 0.0\n" in after
    assert "Secret Client Name" not in before + after
    assert "revrook_schedules_overdue 0\n" in after


async def test_a_late_schedule_is_counted_as_overdue(
    ui_settings: Settings, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    async with factory_of(db_engine)() as session, session.begin():
        session.add(
            Schedule(
                name="late",
                kind="retention-purge",
                cron="@daily",
                next_run_at=NOW - timedelta(minutes=10),
                config={},
            )
        )
    header = {"Authorization": f"Bearer {TOKEN}"}
    async with metrics_app(ui_settings, db_engine, clock, TOKEN) as client:
        response = await client.get("/metrics", headers=header)
    assert "revrook_schedules_enabled 1\n" in response.text
    assert "revrook_schedules_overdue 1\n" in response.text
