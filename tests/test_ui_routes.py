"""The pages of phase 9 over HTTP: the flow, the filter, the status words, the refusals.

These tests need PostgreSQL (DATABASE_URL) and are skipped without it. They use
synthetic data only and no network.
"""

import hashlib
import os
import re
import time
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.models import (
    Client,
    EvidenceItem,
    ExceptionRecord,
    ReportExport,
    Setting,
    Snapshot,
)
from helpers import NOW, create_admin, get_csrf
from ui_helpers import (
    NAME,
    QUARTER,
    STATUS,
    STATUS_SPAN,
    exported_id,
    make_report,
    many_clients,
    page_routes,
    post_export,
    rows_of,
    sample_path,
    seed_client,
    sign_in,
    title_of,
)

CONTROLS = len(load_library().controls)
CONTROL = "PC-ACC-01"
REFRESH_FIRST = re.compile(r'<ol id="refresh-list">\s*<li><strong>(.*?)</strong>')
MAX_SECONDS = 0.5
# The routes are read from the application, so a new page or form of these modules
# is tested here without being added by hand. A form may be given fields below.
GET_ROUTES = page_routes("GET")
POST_ROUTES = page_routes("POST")
POST_FIELDS: dict[str, dict[str, str]] = {
    "/clients": {"name": "Posted Client"},
    "/clients/{client_id}/controls/{control_id}/note": {"did": "A note"},
    "/clients/{client_id}/exceptions": {"control_id": CONTROL},
    "/clients/{client_id}/reports/details": {"plan": "A line"},
    "/clients/{client_id}/reports/{snapshot_id}/export": {"kind": "qbr"},
    "/settings": {"msp_name": "Posted MSP"},
}
GET_PAGES = tuple(sample_path(path) for path in GET_ROUTES)
POSTS = tuple((sample_path(path), POST_FIELDS.get(path, {})) for path in POST_ROUTES)


def test_the_route_lists_are_read_from_the_application() -> None:
    assert len(GET_ROUTES) >= 13 and len(POST_ROUTES) >= 8
    assert "/clients/{client_id}/reports/{snapshot_id}/preview/{kind}" in GET_ROUTES
    assert "/clients/{client_id}/exports/{export_id}/download" in GET_ROUTES
    assert "/clients/{client_id}/reports/snapshot" in POST_ROUTES
    assert set(POST_FIELDS) <= set(POST_ROUTES)
    assert all("{" not in path for path in GET_PAGES)


async def count(engine: AsyncEngine, model: type) -> int:
    async with async_sessionmaker(engine)() as session:
        query = select(func.count()).select_from(model)
        return int((await session.execute(query)).scalar_one())


@pytest.mark.parametrize("path", GET_PAGES)
async def test_a_page_without_a_session_goes_to_the_sign_in_page(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, path: str
) -> None:
    await create_admin(db_engine)
    plain = await ui_browser.get(path)
    assert plain.status_code == 303
    assert plain.headers["location"] == "/login"
    htmx = await ui_browser.get(path, headers={"HX-Request": "true"})
    assert htmx.status_code == 200
    assert htmx.headers["HX-Redirect"] == "/login"
    assert NAME not in plain.text and "Synthetic" not in htmx.text


@pytest.mark.parametrize(("path", "fields"), POSTS)
async def test_a_post_without_a_session_and_a_token_is_403(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    path: str,
    fields: dict[str, str],
) -> None:
    await create_admin(db_engine)
    refused = await ui_browser.post(path, data=fields)
    assert refused.status_code == 403
    assert await count(db_engine, Client) == 0
    assert await count(db_engine, Setting) == 0


@pytest.mark.parametrize(("path", "fields"), POSTS)
async def test_a_post_with_a_token_but_no_user_goes_to_the_sign_in_page(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    path: str,
    fields: dict[str, str],
) -> None:
    await create_admin(db_engine)
    token = await get_csrf(ui_browser, "/login")
    answer = await ui_browser.post(path, data={**fields, "csrf_token": token})
    assert answer.status_code == 303
    assert answer.headers["location"] == "/login"
    assert await count(db_engine, Client) == 0
    assert await count(db_engine, Setting) == 0


@pytest.mark.parametrize(("path", "fields"), POSTS)
async def test_a_post_from_a_signed_in_user_without_a_token_is_403(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    path: str,
    fields: dict[str, str],
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    address = path.replace("/clients/1", f"/clients/{client_id}")
    refused = await ui_browser.post(address, data=fields)
    assert refused.status_code == 403
    assert await count(db_engine, Client) == 1
    assert await count(db_engine, Setting) == 0
    assert await count(db_engine, Snapshot) == 0
    assert await count(db_engine, ReportExport) == 0
    assert await count(db_engine, ExceptionRecord) == 0


async def test_a_client_goes_from_a_period_to_an_exported_review(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    created = await ui_browser.post(
        "/clients", data={"csrf_token": csrf, "name": "Flow Client"}
    )
    assert created.status_code == 303
    listing = await ui_browser.get("/clients")
    assert "Flow Client" in listing.text and "No evidence yet" in listing.text
    client_id = await seed_client(db_engine, ui_ctx)

    overview = await ui_browser.get(
        f"/clients/{client_id}",
        params={"period_start": QUARTER[0], "period_end": QUARTER[1]},
    )
    assert overview.status_code == 200
    assert title_of(overview.text) == f"Overview - {NAME} - revrook"
    assert f"Period {QUARTER[0]} to {QUARTER[1]}" in overview.text
    for fragment in ('id="period-picker"', 'id="summary"', 'id="freshness"'):
        assert fragment in overview.text

    note = await ui_browser.post(
        f"/clients/{client_id}/controls/{CONTROL}/note",
        data={"did": "Enforced it", "recommend": "Keep it on"},
        headers={"HX-Request": "true", "X-CSRF-Token": csrf},
    )
    assert note.status_code == 200 and "Saved at" in note.text
    control = await ui_browser.get(f"/clients/{client_id}/controls/{CONTROL}")
    assert control.status_code == 200 and "Enforced it" in control.text

    report = await make_report(ui_browser, csrf, client_id)
    assert re.fullmatch(rf"/clients/{client_id}/reports/\d+", report)
    page = await ui_browser.get(report)
    assert page.status_code == 200 and "Nothing stops this report" in page.text
    preview = await ui_browser.get(f"{report}/preview/qbr")
    assert preview.status_code == 200
    assert preview.headers["content-security-policy"].startswith("default-src 'none'")
    assert "<script" not in preview.text.lower()
    # Only the top findings carry notes; write one on the first of them.
    top = re.search(r'<span class="secondary">(PC-[A-Z]+-\d+)', preview.text)
    assert top is not None
    await ui_browser.post(
        f"/clients/{client_id}/controls/{top.group(1)}/note",
        data={"did": "Enforced it", "recommend": "Keep it on"},
        headers={"HX-Request": "true", "X-CSRF-Token": csrf},
    )
    preview = await ui_browser.get(f"{report}/preview/qbr")
    assert "Enforced it" in preview.text

    exported = await post_export(ui_browser, csrf, report, "qbr")
    assert exported.status_code == 303
    export_id = exported_id(exported)
    history = await ui_browser.get(f"/clients/{client_id}/exports")
    assert f"/exports/{export_id}/download" in history.text
    address = f"/clients/{client_id}/exports/{export_id}/download"
    download = await ui_browser.get(address)
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith(
        'attachment; filename="qbr-synthetic-client-ltd-'
    )
    digest = hashlib.sha256(download.content).hexdigest()
    assert digest in history.text
    async with async_sessionmaker(db_engine)() as session:
        row = await session.get(ReportExport, export_id)
    assert row is not None and row.file_sha256 == digest
    assert row.client_id == client_id and row.exported_by_id is not None


async def test_every_status_is_an_icon_and_words(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    for path in (
        f"/clients/{client_id}",
        f"/clients/{client_id}/checklist",
        f"/clients/{client_id}/controls/{CONTROL}",
        f"/clients/{client_id}/evidence",
    ):
        page = await ui_browser.get(path)
        assert page.status_code == 200, path
        shown = STATUS_SPAN.findall(page.text)
        found = STATUS.findall(page.text)
        assert shown, path
        assert len(shown) == len(found), f"a status without icon and words on {path}"
        for _, icon, words in found:
            assert icon.strip() and words.strip()


async def test_the_checklist_filter_shows_only_changed_or_flagged_rows(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await make_report(ui_browser, csrf, client_id)
    every = rows_of((await ui_browser.get(f"/clients/{client_id}/checklist")).text)
    assert len(every) == CONTROLS
    narrowed = await ui_browser.get(
        f"/clients/{client_id}/checklist", params={"show": "flagged"}
    )
    assert narrowed.status_code == 200
    shown = rows_of(narrowed.text)
    assert shown
    assert all(changed or flagged for changed, flagged in shown.values())
    assert set(shown) == {
        control for control, (changed, flagged) in every.items() if changed or flagged
    }
    refused = await ui_browser.get(
        f"/clients/{client_id}/checklist", params={"show": "nonsense"}
    )
    assert refused.status_code == 422


async def test_the_imports_page_names_the_stale_export_to_refresh(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get(f"/clients/{client_id}/evidence")
    assert page.status_code == 200
    first = REFRESH_FIRST.search(page.text)
    assert first is not None and first.group(1) == "Backup jobs export"
    assert "Export it again from the source system and import it." in page.text
    assert "Expired" in page.text
    overview = await ui_browser.get(f"/clients/{client_id}")
    assert "See which export to refresh" in overview.text


async def test_an_exception_is_added_listed_and_closed(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    other_id = await seed_client(db_engine, ui_ctx, "Other Client Ltd")
    review = (NOW.date() + timedelta(days=90)).isoformat()
    base = f"/clients/{client_id}/exceptions"
    bad = await ui_browser.post(
        base,
        data={
            "csrf_token": csrf,
            "control_id": "nope",
            "owner": "",
            "reason": "",
            "review_date": "not-a-date",
        },
    )
    assert bad.status_code == 422 and await count(db_engine, ExceptionRecord) == 0
    added = await ui_browser.post(
        base,
        data={
            "csrf_token": csrf,
            "control_id": CONTROL,
            "owner": "Office manager",
            "reason": "Accepted for the test",
            "review_date": review,
        },
    )
    assert added.status_code == 303
    listing = await ui_browser.get(base)
    assert "Office manager" in listing.text and CONTROL in listing.text
    async with async_sessionmaker(db_engine)() as session:
        found = await session.execute(select(ExceptionRecord.id))
        record_id = found.scalar_one()
    wrong = await ui_browser.post(
        f"/clients/{other_id}/exceptions/{record_id}/close", data={"csrf_token": csrf}
    )
    assert wrong.status_code == 404
    closed = await ui_browser.post(
        f"{base}/{record_id}/close", data={"csrf_token": csrf}
    )
    assert closed.status_code == 303
    async with async_sessionmaker(db_engine)() as session:
        row = await session.get(ExceptionRecord, record_id)
    assert row is not None and row.closed_at is not None


async def test_page_render_stays_under_half_a_second_with_100_clients(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    capsys: pytest.CaptureFixture[str],
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await many_clients(db_engine, ui_ctx, 99, evidence=True)
    assert await count(db_engine, Client) == 100
    assert await count(db_engine, EvidenceItem) == 99 + 6
    report = await make_report(ui_browser, csrf, client_id)
    paths = (
        "/clients",
        f"/clients/{client_id}",
        f"/clients/{client_id}/checklist",
        f"/clients/{client_id}/evidence",
        f"/clients/{client_id}/reports",
        report,
    )
    for path in paths:  # the first request of each page builds its template
        assert (await ui_browser.get(path)).status_code == 200
    timings: dict[str, float] = {}
    for path in paths:
        started = time.perf_counter()
        answer = await ui_browser.get(path)
        timings[path] = time.perf_counter() - started
        assert answer.status_code == 200
    runner = os.environ.get("RUNNER_NAME", "local")
    slowest = max(timings.items(), key=lambda item: item[1])
    line = (
        f"phase 9, 100 clients, 105 evidence items: slowest page {slowest[0]} "
        f"{slowest[1]:.3f} s on {runner}"
    )
    with capsys.disabled():
        print(f"\n{line}")
        for path, seconds in timings.items():
            print(f"phase 9 page time {path} {seconds:.3f} s")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::notice title=Page render time::{line}")
    for path, seconds in timings.items():
        assert seconds < MAX_SECONDS, f"{path} took {seconds:.3f} s"


async def test_the_settings_page_saves_the_msp_name(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    empty = await ui_browser.post(
        "/settings", data={"csrf_token": csrf, "msp_name": " "}
    )
    assert empty.status_code == 422
    bell = await ui_browser.post(
        "/settings", data={"csrf_token": csrf, "msp_name": "Bad\x07Name"}
    )
    assert bell.status_code == 422
    saved = await ui_browser.post(
        "/settings", data={"csrf_token": csrf, "msp_name": "Good MSP"}
    )
    assert saved.status_code == 303
    page = await ui_browser.get("/settings")
    assert 'value="Good MSP"' in page.text
    assert (await ui_browser.get("/glossary")).status_code == 200


async def test_a_client_name_with_a_control_character_is_refused(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    for name in ("Bad\x00Name", "Bad\x07Name"):
        refused = await ui_browser.post(
            "/clients", data={"csrf_token": csrf, "name": name}
        )
        assert refused.status_code == 422
        assert "control character" in refused.text
    assert await count(db_engine, Client) == 0


async def test_the_draft_notes_are_saved_for_the_client_and_refuse_bad_text(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    headers = {"HX-Request": "true", "X-CSRF-Token": csrf}
    details = await ui_browser.post(
        f"/clients/{client_id}/reports/details",
        data={"plan": "Roll out MFA\nReview backups", "prepared_by": "Sam"},
        headers=headers,
    )
    assert details.status_code == 200 and "Saved at" in details.text
    builder = await ui_browser.get(f"/clients/{client_id}/reports")
    assert "Roll out MFA" in builder.text and 'value="Sam"' in builder.text
    bad = await ui_browser.post(
        f"/clients/{client_id}/reports/details",
        data={"plan": "Bad\x07line"},
        headers=headers,
    )
    assert bad.status_code == 422 and "control character" in bad.text
    missing = await ui_browser.post(
        f"/clients/{client_id + 1000}/controls/{CONTROL}/note",
        data={"did": "x"},
        headers=headers,
    )
    assert missing.status_code == 404


async def test_a_malformed_address_is_a_4xx_never_a_500(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    for path, status in (
        ("/clients/0", 422),
        ("/clients/abc", 422),
        ("/clients/99999999999999999999", 422),
        (f"/clients/{client_id + 1000}", 404),
        (f"/clients/{client_id}/controls/PC-ZZZ-99", 404),
        (f"/clients/{client_id}/controls/not-a-control", 422),
        (f"/clients/{client_id}/reports/999999", 404),
        (f"/clients/{client_id}/reports/999999/preview/qbr", 404),
        (f"/clients/{client_id}/exports/999999/download", 404),
        (f"/clients/{client_id}", 200),
    ):
        assert (await ui_browser.get(path)).status_code == status, path
    for query in (
        {"period_start": "2026-13-45"},
        {"period_start": "2026-09-30", "period_end": "2026-07-01"},
        {"period_end": (date(2099, 1, 1)).isoformat()},
        {"period_start": "2000-01-01", "period_end": "2026-09-30"},
    ):
        answer = await ui_browser.get(f"/clients/{client_id}", params=query)
        assert answer.status_code == 422, query
