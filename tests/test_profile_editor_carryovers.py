"""Carry-overs from the review of the profile editor (phase 5, part 1).

The editor tests of phase 4 are in test_profile_editor.py; this file adds the tests
the Code Reviewer (THE-297) and the Test Engineer (THE-298) listed as missing, and
the three small fixes they asked for: the preview runs off the event loop and is
not built for an import, a file in which no row can be read cannot be saved, and an
htmx request that is refused shows a message.
"""

import re
import threading
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.service import EvidenceContext
from app.main import create_app
from app.models import ImportProfile
from app.settings import Settings
from app.ui import profiles
from helpers import (
    VENDOR_COLUMNS,
    VENDOR_REQUIRED,
    FakeClock,
    create_admin,
    create_test_client,
    csrf_from,
    login,
    make_context,
    vendor_device_row,
    vendor_header,
    vendor_inventory,
)
from tools.make_fixtures import DOMAIN, to_csv

EDITOR = "/imports/profile-editor"
PROFILE_ID = re.compile(r'data-profile-id="(\d+)"')
CAPTURED = "2026-10-16T12:00"
REQUIRED_ONLY = {key: VENDOR_COLUMNS[key] for key in VENDOR_REQUIRED}


def form(
    client_id: int, csrf: str, chosen: dict[str, str], **extra: str
) -> dict[str, str]:
    fields = {
        "csrf_token": csrf,
        "client_id": str(client_id),
        "source_code": "device-inventory",
    }
    for key, header in chosen.items():
        fields[f"map-{key}"] = header
    fields.update(extra)
    return fields


async def post(
    browser: httpx.AsyncClient,
    action: str,
    fields: dict[str, str],
    data: bytes,
    htmx: bool = False,
) -> httpx.Response:
    headers = {"HX-Request": "true"} if htmx else {}
    files = {"file": ("vendor.csv", data, "text/csv")}
    return await browser.post(
        f"{EDITOR}/{action}", data=fields, files=files, headers=headers
    )


async def signed_in(
    browser: httpx.AsyncClient, engine: AsyncEngine, ctx: EvidenceContext
) -> tuple[int, str]:
    """Sign in, create a client, and return its id and the page's CSRF token."""
    await create_admin(engine)
    assert (await login(browser)).status_code == 303
    client_id = await create_test_client(engine, ctx)
    page = await browser.get(EDITOR)
    assert page.status_code == 200, page.text
    return client_id, csrf_from(page.text)


async def profile_count(engine: AsyncEngine) -> int:
    query = select(func.count()).select_from(ImportProfile)
    async with async_sessionmaker(engine)() as session:
        return int((await session.execute(query)).scalar_one())


@pytest.fixture
def editor_settings(settings: Settings, tmp_path: Path) -> Settings:
    return replace(settings, evidence_dir=str(tmp_path / "evidence"))


@pytest.fixture
async def browser(
    editor_settings: Settings, db_engine: AsyncEngine, clock: FakeClock
) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(editor_settings, engine=db_engine, clock=clock)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest.fixture
def ctx(editor_settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(editor_settings, tmp_path / "ctx")


async def test_the_preview_runs_off_the_event_loop_and_an_import_builds_none(
    browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    loop_thread = threading.current_thread().name
    calls: list[str] = []
    real = profiles.build_preview

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(threading.current_thread().name)
        return real(*args, **kwargs)

    monkeypatch.setattr(profiles, "build_preview", spy)
    data = vendor_inventory()
    shown = await post(browser, "preview", form(client_id, csrf, VENDOR_COLUMNS), data)
    assert shown.status_code == 200
    assert calls
    assert calls[0] != loop_thread
    named = form(client_id, csrf, VENDOR_COLUMNS, name="Spy")
    saved = PROFILE_ID.search((await post(browser, "save", named, data)).text)
    assert saved is not None
    built = len(calls)
    extra = {"profile_id": saved.group(1), "captured_at": CAPTURED}
    fields = form(client_id, csrf, VENDOR_COLUMNS, **extra)
    imported = await post(browser, "import", fields, data, htmx=True)
    assert imported.status_code == 201, imported.text
    assert "evidence item" in imported.text
    assert len(calls) == built


async def test_a_file_in_which_no_row_can_be_read_cannot_be_saved(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    rows = [vendor_device_row(f"v{n}", f"contact ops{n}@{DOMAIN}") for n in range(3)]
    data = to_csv(vendor_header(), rows)
    fields = form(client_id, csrf, REQUIRED_ONLY, name="Nothing readable")
    shown = await post(browser, "preview", fields, data)
    assert shown.status_code == 200
    assert 'id="rv-problem"' in shown.text
    assert "No row of the file could be read." in shown.text
    assert "3 row(s) shown, 3 of them rejected." in shown.text
    refused = await post(browser, "save", fields, data, htmx=True)
    assert refused.status_code == 422
    expected = "The profile was not saved. No row of the file could be read."
    assert expected in refused.text
    assert await profile_count(db_engine) == 0


async def test_a_text_that_is_only_an_at_sign_and_a_domain_rejects_its_row(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    rows = [vendor_device_row("v1", "@acme.com"), vendor_device_row("v2", "Shield")]
    data = to_csv(vendor_header(), rows)
    fields = form(client_id, csrf, REQUIRED_ONLY)
    shown = await post(browser, "preview", fields, data, htmx=True)
    assert shown.status_code == 200
    assert "2 row(s) shown, 1 of them rejected." in shown.text
    assert "Rejected: av_product must not contain an email address" in shown.text
    assert "acme.com" not in shown.text


async def test_a_very_wide_file_is_previewed_and_its_extra_columns_are_not_offered(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    extra_columns = [f"extra{number}" for number in range(3000)]
    header = [*vendor_header(), *extra_columns]
    row = [*vendor_device_row("v1", "Shield"), *["x"] * len(extra_columns)]
    fields = form(client_id, csrf, REQUIRED_ONLY)
    shown = await post(browser, "preview", fields, to_csv(header, [row]))
    assert shown.status_code == 200
    assert "2809 column(s) of the file are not offered" in shown.text
    assert "1 row(s) shown, 0 of them rejected." in shown.text


async def test_a_file_that_is_not_utf8_is_read_or_refused_never_an_error(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    text = "Machine,Platform,Seen at\nvéry-odd,Wíndows,2026-10-16T08:00:00Z\n"
    files = [
        text.encode("latin-1"),
        text.encode("utf-16-le"),
        b"\xff\xfe\x00\xd8garbage\x80\x81",
    ]
    for data in files:
        answer = await post(browser, "preview", form(client_id, csrf, {}), data)
        assert answer.status_code in (200, 422), data
        assert "Traceback" not in answer.text


async def test_a_file_over_the_limit_that_passes_the_size_middleware_is_refused_413(
    editor_settings: Settings,
    db_engine: AsyncEngine,
    clock: FakeClock,
    ctx: EvidenceContext,
) -> None:
    # 1,500 bytes is above the 1,000 byte limit and far below the middleware's cap
    # (limit plus 64 KB of form overhead), so the handler itself refuses it.
    app = create_app(replace(editor_settings, import_max_bytes=1000), db_engine, clock)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as small:
        client_id, csrf = await signed_in(small, db_engine, ctx)
        fields = form(client_id, csrf, VENDOR_COLUMNS)
        refused = await post(small, "preview", fields, b"x" * 1500)
    assert refused.status_code == 413
    assert "The file is larger than the limit" in refused.text


async def test_an_htmx_request_that_is_refused_gets_a_message_not_json(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, _ = await signed_in(browser, db_engine, ctx)
    fields = form(client_id, "", VENDOR_COLUMNS)
    del fields["csrf_token"]
    data = vendor_inventory()
    refused = await post(browser, "preview", fields, data, htmx=True)
    assert refused.status_code == 403
    assert refused.headers["content-type"].startswith("text/html")
    assert 'class="rv-errors"' in refused.text
    assert "Reload the page" in refused.text
    plain = await post(browser, "preview", fields, data)
    assert plain.status_code == 403
    assert plain.headers["content-type"].startswith("application/json")
    page = await browser.get(EDITOR)
    assert "(403|409|413|422|500)" in page.text
