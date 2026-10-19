"""Carry-overs of the phase 9 checks (THE-321, THE-322) and ROLE=all (phase 10).

These tests need PostgreSQL (DATABASE_URL) and are skipped without it. They use
synthetic data only; the only process they start is this application, on 127.0.0.1.
"""

import asyncio
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import cli
from app.db import make_engine
from app.evidence.assurance import Assurance
from app.evidence.service import EvidenceContext, NewEvidence
from app.models import Client, ExceptionRecord, Snapshot
from app.reports.topics import TOPIC_KEYS
from app.textcheck import control_character
from helpers import NOW, create_admin, issue_token, upload
from html_structure import structure_problems
from tools import make_generic_fixtures
from ui_helpers import make_report, seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
CONTROL = "PC-ACC-01"
# Letters that are real writing and stay allowed in a name: accents, Chinese,
# Arabic, Hebrew, and Persian with the zero-width non-joiner (U+200C) and a soft
# hyphen (U+00AD) inside the word.
LEGITIMATE_NAMES = [
    "José Álvarez & Hijos S.L.",
    "株式会社テスト",
    "شركة النور للتقنية",
    "חברת אור בע״מ",
    "شرکت می‌خواهم",
    "Mo­ore Ltd",
    "Zoë O’Brien-Łukasiewicz",
]
# Bidi controls, zero-width space, word joiner and the byte order mark (O-5).
REFUSED_IN_TEXT = ["‮", "​", "⁠", "﻿", "‏", "⁦"]


async def count(engine: AsyncEngine, model: type) -> int:
    async with async_sessionmaker(engine)() as session:
        query = select(func.count()).select_from(model)
        return int((await session.execute(query)).scalar_one())


# --- N-1 / O-4: legitimate names stay allowed ---


@pytest.mark.parametrize("name", LEGITIMATE_NAMES)
def test_a_legitimate_non_ascii_name_passes_the_text_check(name: str) -> None:
    assert control_character(name) is None
    assert control_character(name, allow_breaks=True) is None


@pytest.mark.parametrize("name", LEGITIMATE_NAMES)
async def test_a_client_with_a_legitimate_non_ascii_name_is_created(
    client: httpx.AsyncClient, db_engine: AsyncEngine, name: str
) -> None:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    made = await client.post("/api/v1/clients", headers=token, json={"name": name})
    assert made.status_code == 201, made.text
    assert made.json()["name"] == name
    async with async_sessionmaker(db_engine)() as session:
        stored = await session.execute(select(Client.name))
        assert list(stored.scalars()) == [name]


# --- O-5: no invisible or reordering character in any text of a report ---


@pytest.mark.parametrize("character", REFUSED_IN_TEXT)
async def test_the_preparer_and_a_topic_owner_refuse_invisible_characters(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    character: str,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    path = f"/clients/{client_id}/reports/details"
    for field in ("prepared_by", f"owner-{TOPIC_KEYS[0]}"):
        refused = await ui_browser.post(
            path, data={"csrf_token": csrf, field: f"Pat{character}Quill"}
        )
        assert refused.status_code == 422, field
        assert "control character" in refused.text, field
    saved = await ui_browser.post(
        path,
        data={
            "csrf_token": csrf,
            "prepared_by": "Pat Quill",
            f"owner-{TOPIC_KEYS[0]}": "Sam Ortiz",
            "plan": "First line\nSecond line",
        },
    )
    assert saved.status_code == 303


@pytest.mark.parametrize("character", REFUSED_IN_TEXT)
async def test_an_exception_owner_reason_and_control_refuse_invisible_characters(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    character: str,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    path = f"/clients/{client_id}/exceptions"
    good = {
        "csrf_token": csrf,
        "control_id": CONTROL,
        "owner": "Pat Quill",
        "reason": "Accepted for now",
        "compensating_control": "A weekly review",
        "review_date": "2026-12-01",
    }
    for field in ("owner", "reason", "compensating_control"):
        refused = await ui_browser.post(path, data={**good, field: f"a{character}b"})
        assert refused.status_code == 422, field
    assert await count(db_engine, ExceptionRecord) == 0
    # A normal line break in the reason is still fine.
    accepted = await ui_browser.post(
        path, data={**good, "reason": "Line one\r\nLine two"}
    )
    assert accepted.status_code == 303
    assert await count(db_engine, ExceptionRecord) == 1


# --- N-2: the signed-out pages go through the structure check ---


async def test_the_first_run_page_has_a_sound_structure_when_no_user_exists(
    client: httpx.AsyncClient,
) -> None:
    setup = await client.get("/setup")
    assert setup.status_code == 200
    assert structure_problems(setup.text) == []
    assert "<title>" in setup.text and 'name="csrf_token"' in setup.text
    # With no user the sign-in page is not shown: it leads to the first run page.
    login = await client.get("/login")
    assert login.status_code == 303 and login.headers["location"] == "/setup"


async def test_the_sign_in_page_has_a_sound_structure_once_a_user_exists(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    login = await client.get("/login")
    assert login.status_code == 200
    assert structure_problems(login.text) == []
    assert 'name="username"' in login.text and 'name="csrf_token"' in login.text
    # The first run page is closed once there is a user.
    setup = await client.get("/setup")
    assert setup.status_code == 303 and setup.headers["location"] == "/login"


# --- N-4: the 30 second twin of a snapshot belongs to one client and one state ---


async def test_another_client_with_the_same_state_gets_its_own_snapshot(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    first = await seed_client(db_engine, ui_ctx, "First Twin Ltd")
    second = await seed_client(db_engine, ui_ctx, "Second Twin Ltd")
    one = await make_report(ui_browser, csrf, first)
    # Seconds later, the other client has identical evidence and the same period.
    other = await make_report(ui_browser, csrf, second)
    assert one.startswith(f"/clients/{first}/reports/")
    assert other.startswith(f"/clients/{second}/reports/")
    assert one.rsplit("/", 1)[1] != other.rsplit("/", 1)[1]
    async with async_sessionmaker(db_engine)() as session:
        found = await session.execute(select(Snapshot.client_id).order_by(Snapshot.id))
        owners = list(found.scalars())
    assert owners == [first, second]
    # A second click for the first client inside the 30 seconds still opens its report.
    again = await make_report(ui_browser, csrf, first)
    assert again == one
    assert await count(db_engine, Snapshot) == 2


async def test_new_evidence_within_30_seconds_makes_a_new_snapshot(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    before = await make_report(ui_browser, csrf, client_id)
    # A newer device inventory arrives; no clock time passes at all.
    variant = make_generic_fixtures.device_inventory_csv(
        seed=make_generic_fixtures.SEED + 1
    )
    evidence = NewEvidence(
        source_code=variant.source_code,
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=NOW - timedelta(days=1),
        data=variant.data,
    )
    await upload(db_engine, ui_ctx, client_id, evidence, NOW)
    after = await make_report(ui_browser, csrf, client_id)
    assert after != before
    assert await count(db_engine, Snapshot) == 2
    # With nothing new, the next click is a twin of the second snapshot.
    assert await make_report(ui_browser, csrf, client_id) == after
    assert await count(db_engine, Snapshot) == 2


# --- check 7: ROLE=all starts web and worker, and /readyz reflects the heartbeat ---


def test_the_all_role_runs_the_web_role_and_the_worker_as_two_commands() -> None:
    web, worker = cli.all_commands(9123)
    assert web[1:] == ["-m", "app.cli", "web", "--port", "9123"]
    assert worker[1:] == ["-m", "app.cli", "worker"]
    assert web[0] == worker[0] == sys.executable


def test_the_web_and_all_commands_take_a_port() -> None:
    parser = cli._build_parser()
    assert parser.parse_args(["web"]).port == cli.PORT
    assert parser.parse_args(["all", "--port", "9000"]).port == 9000
    assert not hasattr(parser.parse_args(["worker"]), "port")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def fetch(url: str) -> tuple[int, dict[str, str]]:
    """The status and the JSON of a GET; (0, {}) while nothing listens yet."""
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")
    except OSError:
        return 0, {}


async def test_role_all_starts_web_and_worker_and_readyz_follows_the_heartbeat(
    database_url: str, migrated_database: str, tmp_path: Path
) -> None:
    engine = make_engine(migrated_database)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE worker_heartbeat"))
    port = free_port()
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "SECRET_KEY": "test-only-secret-key-0123456789",
        "FERNET_KEY": base64.urlsafe_b64encode(bytes(32)).decode(),
        "ROLE": "all",
        "EVIDENCE_DIR": str(tmp_path / "evidence"),
        "LOG_LEVEL": "warning",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "app.cli", "all", "--port", str(port)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    seen: list[tuple[int, dict[str, str]]] = []
    try:
        for _ in range(80):
            answer = await asyncio.to_thread(fetch, f"http://127.0.0.1:{port}/readyz")
            seen.append(answer)
            if answer[0] == 200 or process.poll() is not None:
                break
            await asyncio.sleep(0.5)
        assert process.poll() is None, "the all role exited"
        # The web role answers, and it is ready only because the worker reported.
        assert seen[-1] == (
            200,
            {"status": "ready", "database": "ok", "worker": "running"},
        )
        async with engine.connect() as connection:
            query = text("SELECT detail->>'role' FROM worker_heartbeat")
            roles = list((await connection.execute(query)).scalars())
            assert roles == ["all"]
        # Every earlier answer was a refusal that named the missing worker, not a pass.
        assert all(status in (0, 503) for status, _ in seen[:-1])
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            await asyncio.to_thread(process.wait, 30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        await engine.dispose()
    assert process.returncode == 0
