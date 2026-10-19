"""Carry-overs of the phase 10 checks (THE-330, THE-331), phase 11 part 1 (THE-332).

These tests need PostgreSQL (DATABASE_URL) and are skipped without it, except the
ones that read files. They use synthetic data only; nothing here leaves the machine.
"""

import asyncio
import io
import zipfile
from functools import partial

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.dataexport import build_export
from app.evidence.service import EvidenceContext
from app.limits import MAX_BODY_BYTES
from app.main import OUT_OF_RANGE
from app.models import Schedule
from helpers import (
    NOW,
    audit_baseline,
    audit_since,
    create_test_client,
    export_evidence,
    issue_token,
    login,
    upload,
)
from repo_files import ROOT, source_files
from ui_helpers import make_report, seed_client, sign_in

CONTROL = "PC-ACC-01"
OVER_RANGE = [2**63, 99_999_999_999_999_999_999]
# Characters that hide or reorder text: the soft hyphen, the zero-width and direction
# marks, the bidi embeddings and overrides, the invisible operators and the bidi
# isolates. Written as code points so that this file holds none of them itself.
INVISIBLE = tuple(
    chr(point)
    for point in (
        0x00AD,
        *range(0x200B, 0x2010),
        *range(0x202A, 0x202F),
        *range(0x2060, 0x2065),
        *range(0x2066, 0x206A),
    )
)
BYTE_ORDER_MARK = chr(0xFEFF)
# Files that hold a byte order mark on purpose: the importers read one, and their
# tests write one.
BYTE_ORDER_MARK_FILES = {
    "app/importers/framework.py",
    "tests/test_importer_framework.py",
    "tests/test_importers.py",
}


async def bearer(engine: AsyncEngine) -> dict[str, str]:
    return {"Authorization": f"Bearer {await issue_token(engine)}"}


def read_zip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


# --- A1: an id past the database range is refused, never a 500 ---


@pytest.mark.parametrize("big", OVER_RANGE)
async def test_an_id_past_the_database_range_is_refused_never_a_500(
    client: httpx.AsyncClient, db_engine: AsyncEngine, big: int
) -> None:
    token = await bearer(db_engine)
    schedule = {"kind": "snapshot-build", "cron": "@daily", "client_id": big}
    answers = [
        await client.delete(f"/api/v1/schedules/{big}", headers=token),
        await client.post(f"/api/v1/clients/{big}/snapshot-requests", headers=token),
        await client.post("/api/v1/schedules", headers=token, json=schedule),
        await client.get(f"/api/v1/clients/{big}/evidence", headers=token),
        await client.get(f"/api/v1/clients/{big}/evidence/chain", headers=token),
        await client.get(f"/api/v1/clients/{big}/dns-check", headers=token),
        await client.delete(f"/api/v1/clients/{big}", headers=token),
    ]
    assert [answer.status_code for answer in answers] == [422] * len(answers)


@pytest.mark.parametrize("small", [0, -1])
async def test_an_id_below_one_is_refused_too(
    client: httpx.AsyncClient, db_engine: AsyncEngine, small: int
) -> None:
    token = await bearer(db_engine)
    schedule = {"kind": "snapshot-build", "cron": "@daily", "client_id": small}
    answers = [
        await client.delete(f"/api/v1/schedules/{small}", headers=token),
        await client.post("/api/v1/schedules", headers=token, json=schedule),
    ]
    assert [answer.status_code for answer in answers] == [422, 422]


async def test_the_largest_id_is_a_404_not_an_error(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    largest = 2**63 - 1
    gone = await client.delete(f"/api/v1/schedules/{largest}", headers=token)
    assert gone.status_code == 404
    request = await client.post(
        f"/api/v1/clients/{largest}/snapshot-requests", headers=token
    )
    assert request.status_code == 404


async def test_a_data_error_that_gets_through_is_422_not_500(
    web_app: FastAPI, client: httpx.AsyncClient
) -> None:
    async def boom() -> None:
        raise DataError("SELECT 1", {}, Exception("value out of range"))

    web_app.add_api_route("/boom", boom)
    answer = await client.get("/boom")
    assert answer.status_code == 422
    assert answer.json() == {"detail": OUT_OF_RANGE}
    page = await client.get("/boom", headers={"HX-Request": "true"})
    assert page.status_code == 422
    assert "outside what revrook can store" in page.text


# --- A3: two snapshot requests at once queue one snapshot ---


async def test_two_snapshot_requests_at_once_queue_one(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    made = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Race Test Ltd"}
    )
    path = f"/api/v1/clients/{made.json()['id']}/snapshot-requests"
    answers = await asyncio.gather(
        client.post(path, headers=token), client.post(path, headers=token)
    )
    assert [answer.status_code for answer in answers] == [202, 202]
    assert sorted(answer.json()["queued"] for answer in answers) == [False, True]
    assert len({answer.json()["id"] for answer in answers}) == 1
    async with async_sessionmaker(db_engine)() as session:
        query = select(func.count()).select_from(Schedule)
        waiting = await session.execute(query.where(Schedule.kind == "snapshot-build"))
        assert waiting.scalar_one() == 1


async def test_a_second_request_after_the_worker_took_the_first_queues_again(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    made = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Again Test Ltd"}
    )
    path = f"/api/v1/clients/{made.json()['id']}/snapshot-requests"
    first = await client.post(path, headers=token)
    assert first.json()["queued"] is True
    # The worker claims a one-time schedule by switching it off.
    async with async_sessionmaker(db_engine)() as session, session.begin():
        row = await session.get(Schedule, first.json()["id"])
        assert row is not None
        row.enabled = False
    second = await client.post(path, headers=token)
    assert second.status_code == 202 and second.json()["queued"] is True
    assert second.json()["id"] != first.json()["id"]


# --- A4: the export is streamed and capped ---


async def test_the_export_is_the_same_when_it_spills_to_disk_in_tiny_chunks(
    client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = await create_test_client(db_engine, ui_ctx, "Export Test Ltd")
    await upload(db_engine, ui_ctx, client_id, export_evidence(), NOW)
    token = await bearer(db_engine)
    normal = await client.get("/api/v1/export", headers=token)
    assert normal.status_code == 200
    # One byte of memory before the file goes to disk, one byte per write.
    monkeypatch.setattr("app.dataexport.SPOOL_BYTES", 1)
    monkeypatch.setattr("app.dataexport.CHUNK_BYTES", 1)
    spilled = await client.get("/api/v1/export", headers=token)
    assert spilled.status_code == 200
    assert int(spilled.headers["content-length"]) == len(spilled.content)
    first, second = read_zip(normal.content), read_zip(spilled.content)
    assert set(first) == set(second) and len(first) >= 13
    for name in (
        "clients.csv",
        "evidence_items.csv",
        "evidence_revisions.csv",
        "facts.csv",
        "evidence_log.csv",
    ):
        assert first[name] == second[name], name
    assert b"Export Test Ltd" in second["clients.csv"]


async def test_an_export_over_the_cap_is_413_and_is_not_audited(
    client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await create_test_client(db_engine, ui_ctx, "Cap Test Ltd")
    token = await bearer(db_engine)
    monkeypatch.setattr(
        "app.api_ops.build_export", partial(build_export, max_bytes=100)
    )
    baseline = await audit_baseline(db_engine)
    refused = await client.get("/api/v1/export", headers=token)
    assert refused.status_code == 413
    assert "database backup" in refused.json()["detail"]
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events if event.action == "data.exported"] == []


async def test_the_system_page_shows_the_refusal_of_an_export_over_the_cap(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    monkeypatch.setattr(
        "app.api_ops.build_export", partial(build_export, max_bytes=100)
    )
    refused = await ui_browser.post("/system/export", data={"csrf_token": csrf})
    assert refused.status_code == 413
    assert "database backup" in refused.text


# --- A5: a body over the limit is refused with 413 ---


async def test_a_request_body_over_one_mebibyte_is_413_before_anything_reads_it(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = await bearer(db_engine)
    big = b"x" * (MAX_BODY_BYTES + 1)
    refused = await client.post("/api/v1/clients", headers=token, content=big)
    assert refused.status_code == 413
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    signin = await client.post("/login", headers=form, content=big)
    assert signin.status_code == 413
    small = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Small Body Ltd"}
    )
    assert small.status_code == 201


# --- A6: a report period has a documented maximum ---


async def test_a_report_period_over_400_days_is_422_and_400_days_is_not(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    end = "2026-09-30"
    too_long = {"period_start": "2025-08-25", "period_end": end}
    refused = await ui_browser.post(
        f"/clients/{client_id}/reports/snapshot", data={"csrf_token": csrf, **too_long}
    )
    assert refused.status_code == 422
    assert "longer than 400 days" in refused.text
    for path in (f"/clients/{client_id}", f"/clients/{client_id}/reports"):
        page = await ui_browser.get(path, params=too_long)
        assert page.status_code == 422, path
    longest = {"period_start": "2025-08-26", "period_end": end}
    accepted = await ui_browser.post(
        f"/clients/{client_id}/reports/snapshot", data={"csrf_token": csrf, **longest}
    )
    assert accepted.status_code == 303


# --- A7: notes are saved as they are typed, so the end of a session loses none ---


async def test_notes_saved_before_the_session_ended_are_there_after_signing_in_again(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    path = f"/clients/{client_id}/controls/{CONTROL}"
    htmx = {"HX-Request": "true", "X-CSRF-Token": csrf}
    saved = await ui_browser.post(
        f"{path}/note", data={"did": "Enforced it for admins"}, headers=htmx
    )
    assert saved.status_code == 200 and "Saved at" in saved.text
    # The session ends: 12 hours pass, or the cookie is gone.
    ui_browser.cookies.clear()
    gone = await ui_browser.get(path)
    assert gone.status_code == 303 and gone.headers["location"] == "/login"
    # What is typed after that is refused with a readable message, not half saved.
    late = await ui_browser.post(
        f"{path}/note", data={"did": "Typed too late"}, headers=htmx
    )
    assert late.status_code == 403 and "session has ended" in late.text
    assert (await login(ui_browser)).status_code == 303
    page = await ui_browser.get(path)
    assert page.status_code == 200
    assert "Enforced it for admins" in page.text
    assert "Typed too late" not in page.text


async def test_the_report_details_survive_the_end_of_a_session(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)
    details = await ui_browser.post(
        f"/clients/{client_id}/reports/details",
        data={"csrf_token": csrf, "prepared_by": "Pat Quill", "plan": "Renew MFA"},
    )
    assert details.status_code == 303
    ui_browser.cookies.clear()
    assert (await login(ui_browser)).status_code == 303
    builder = await ui_browser.get(f"/clients/{client_id}/reports")
    assert "Pat Quill" in builder.text and "Renew MFA" in builder.text
    assert (await ui_browser.get(report)).status_code == 200


# --- A8: no hidden character in any source file ---


def test_no_source_file_holds_a_hidden_or_reordering_character() -> None:
    files = source_files()
    assert len(files) > 100
    offenders: list[str] = []
    marks: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        name = path.relative_to(ROOT).as_posix()
        for character in INVISIBLE:
            if character in text:
                offenders.append(f"{name} holds U+{ord(character):04X}")
        if BYTE_ORDER_MARK in text:
            marks.add(name)
    assert offenders == []
    # The byte order mark is allowed only where an importer reads one.
    assert marks <= BYTE_ORDER_MARK_FILES, sorted(marks - BYTE_ORDER_MARK_FILES)
