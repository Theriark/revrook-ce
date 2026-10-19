"""The mapping profile editor page through HTTP (synthetic data only)."""

import re
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
from app.models import Fact, ImportProfile
from app.settings import Settings
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
from tools import make_generic_fixtures
from tools.make_fixtures import DOMAIN, to_csv
from tools.make_generic_fixtures import CLIENT_LABEL, HOSTNAME_PREFIX, SERIAL_PREFIX

EDITOR = "/imports/profile-editor"
TITLE = re.compile(r"<title>(.*?)</title>")
PROFILE_ID = re.compile(r'data-profile-id="(\d+)"')
ITEM_ID = re.compile(r'data-item-id="(\d+)"')
CAPTURED = "2026-10-16T12:00"
INVENTORY = make_generic_fixtures.device_inventory_csv()
REQUIRED_ONLY = {key: VENDOR_COLUMNS[key] for key in VENDOR_REQUIRED}


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


async def summary_of(engine: AsyncEngine, item_id: int) -> dict[str, Any]:
    query = select(Fact.value).where(
        Fact.evidence_item_id == item_id, Fact.fact_key == "inventory.summary"
    )
    async with async_sessionmaker(engine)() as session:
        value: dict[str, Any] = (await session.execute(query)).scalar_one()
    return value


async def profile_count(engine: AsyncEngine) -> int:
    query = select(func.count()).select_from(ImportProfile)
    async with async_sessionmaker(engine)() as session:
        return int((await session.execute(query)).scalar_one())


async def test_the_page_needs_a_signed_in_user(browser: httpx.AsyncClient) -> None:
    page = await browser.get(EDITOR)
    assert page.status_code == 303
    assert page.headers["location"] == "/login"


async def test_the_page_uses_the_brand_layout(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    await signed_in(browser, db_engine, ctx)
    page = await browser.get(EDITOR)
    match = TITLE.search(page.text)
    assert match is not None
    assert match.group(1) == "Profile editor - revrook"
    assert 'class="rv-header"' in page.text
    # The stylesheet link carries the asset version (?v=<digest>), see brand.py.
    assert 'href="/static/css/revrook.css?v=' in page.text
    assert 'alt="revrook"' in page.text or 'class="rv-wordmark"' in page.text
    assert 'href="/imports/profile-editor" aria-current="page"' in page.text
    assert 'name="csrf_token"' in page.text
    assert 'enctype="multipart/form-data"' in page.text
    assert "Synthetic Client Ltd" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    home = await browser.get("/")
    assert 'href="/imports/profile-editor"' in home.text


async def test_a_post_without_the_csrf_token_is_refused(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, _ = await signed_in(browser, db_engine, ctx)
    data = vendor_inventory()
    fields = form(client_id, "", VENDOR_COLUMNS, name="No token")
    del fields["csrf_token"]
    for action in ("preview", "save", "import"):
        refused = await post(browser, action, fields, data)
        assert refused.status_code == 403, action
    wrong = form(client_id, "not-the-token", VENDOR_COLUMNS, name="Wrong token")
    assert (await post(browser, "save", wrong, data)).status_code == 403
    assert await profile_count(db_engine) == 0


async def test_a_vendor_file_round_trips_to_the_counts_of_the_canonical_fixture(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    data = vendor_inventory()

    shown = await post(browser, "preview", form(client_id, csrf, VENDOR_COLUMNS), data)
    assert shown.status_code == 200, shown.text
    assert 'id="rv-preview"' in shown.text
    assert "10 row(s) shown, 0 of them rejected." in shown.text
    assert 'id="rv-utc-note"' in shown.text
    assert "UTC assumed" in shown.text
    assert '<option value="Machine" selected>Machine</option>' in shown.text
    for value in (DOMAIN, SERIAL_PREFIX, CLIENT_LABEL, HOSTNAME_PREFIX):
        assert value not in shown.text

    named = form(client_id, csrf, VENDOR_COLUMNS, name="Vendor inventory")
    saved = await post(browser, "save", named, data)
    assert saved.status_code == 201, saved.text
    found = PROFILE_ID.search(saved.text)
    assert found is not None
    profile_id = found.group(1)
    async with async_sessionmaker(db_engine)() as session:
        profile = await session.get(ImportProfile, int(profile_id))
    assert profile is not None
    assert profile.client_id == client_id
    assert profile.mapping == {header: key for key, header in VENDOR_COLUMNS.items()}

    extra = {"profile_id": profile_id, "captured_at": CAPTURED}
    fields = form(client_id, csrf, VENDOR_COLUMNS, **extra)
    imported = await post(browser, "import", fields, data, htmx=True)
    assert imported.status_code == 201, imported.text
    assert "<html" not in imported.text
    item = ITEM_ID.search(imported.text)
    assert item is not None
    assert f"{INVENTORY.facts} facts stored" in imported.text
    assert await summary_of(db_engine, int(item.group(1))) == INVENTORY.expected

    again = await post(browser, "import", fields, data, htmx=True)
    assert again.status_code == 409
    assert "already uploaded" in again.text


async def test_a_missing_required_column_is_named_and_refused_with_422(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    chosen = {key: header for key, header in VENDOR_COLUMNS.items() if key != "os"}
    data = vendor_inventory()
    fields = form(client_id, csrf, chosen, name="Without the system")
    shown = await post(browser, "preview", fields, data)
    assert shown.status_code == 200
    assert 'id="rv-missing"' in shown.text
    assert "<li>os</li>" in shown.text
    refused = await post(browser, "save", fields, data, htmx=True)
    assert refused.status_code == 422
    expected = "The profile was not saved. The file is missing the column os."
    assert expected in refused.text
    assert await profile_count(db_engine) == 0

    named = form(client_id, csrf, VENDOR_COLUMNS, name="Vendor inventory")
    saved = PROFILE_ID.search((await post(browser, "save", named, data)).text)
    assert saved is not None
    extra = {"profile_id": saved.group(1), "captured_at": CAPTURED}
    renamed = data.replace(b"Platform", b"Operating", 1)
    fields = form(client_id, csrf, VENDOR_COLUMNS, **extra)
    imported = await post(browser, "import", fields, renamed)
    assert imported.status_code == 422
    assert "missing the column os" in imported.text


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"client_id": ""}, "Choose a client."),
        ({"client_id": "12abc"}, "must be a whole number"),
        ({"client_id": "9" * 19}, "must be a whole number"),
        ({"client_id": "999999"}, "There is no client with this id."),
        ({"source_code": "secure-score"}, "Choose one of the listed sources."),
        ({"name": ""}, "The profile name must be 1 to 100 characters."),
    ],
)
async def test_a_wrong_form_field_is_refused_with_422(
    browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    changes: dict[str, str],
    message: str,
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    fields = {**form(client_id, csrf, VENDOR_COLUMNS, name="Profile"), **changes}
    refused = await post(browser, "save", fields, vendor_inventory())
    assert refused.status_code == 422
    assert message in refused.text


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"captured_at": CAPTURED}, "Choose a saved profile to import with."),
        ({"profile_id": "424242", "captured_at": CAPTURED}, "no such mapping profile"),
        ({"profile_id": "1", "captured_at": "yesterday"}, "The capture time must be"),
    ],
)
async def test_an_import_needs_a_saved_profile_and_a_capture_time(
    browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    extra: dict[str, str],
    message: str,
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    fields = form(client_id, csrf, VENDOR_COLUMNS, **extra)
    refused = await post(browser, "import", fields, vendor_inventory())
    assert refused.status_code == 422, refused.text
    assert message in refused.text


async def test_a_post_without_a_file_or_with_json_is_refused(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    fields = form(client_id, csrf, VENDOR_COLUMNS)
    without = await browser.post(f"{EDITOR}/preview", data=fields)
    assert without.status_code == 422
    assert "Choose a file to read." in without.text
    empty = await post(browser, "preview", fields, b"")
    assert empty.status_code == 422
    as_json = await post(browser, "preview", fields, b'{"value": []}')
    assert as_json.status_code == 422
    assert "must be a CSV file" in as_json.text


async def test_hostile_cells_are_escaped_and_neutralised_in_the_preview(
    browser: httpx.AsyncClient, db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id, csrf = await signed_in(browser, db_engine, ctx)
    header = [*vendor_header(), '<img src=x onerror="alert(1)">']
    rows = [
        [*vendor_device_row("vendor-1", "=HYPERLINK(1)"), "a"],
        [*vendor_device_row("vendor-2", "<script>alert(1)</script>"), "b"],
        [*vendor_device_row("vendor-3", "<b>bold</b>" + "A" * 5000), "c"],
        [*vendor_device_row("vendor-4", f"ops@{DOMAIN}"), "d"],
    ]
    fields = form(client_id, csrf, REQUIRED_ONLY)
    shown = await post(browser, "preview", fields, to_csv(header, rows), htmx=True)
    assert shown.status_code == 200, shown.text
    page = shown.text
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<b>bold</b>" not in page
    assert "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "A" * 101 not in page
    assert "&#39;=HYPERLINK(1)" in page
    assert "<img src=x" not in page
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in page
    assert DOMAIN not in page
    assert "Rejected: av_product must not contain an email address" in page
    assert "4 row(s) shown, 1 of them rejected." in page


async def test_a_signed_out_post_is_sent_to_the_sign_in_page(
    browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    page = await browser.get("/login")
    fields = {"csrf_token": csrf_from(page.text), "client_id": "1"}
    from_htmx = await post(browser, "preview", fields, b"a\n", htmx=True)
    assert from_htmx.status_code == 200
    assert from_htmx.headers["hx-redirect"] == "/login"
    plain = await post(browser, "preview", fields, b"a\n")
    assert plain.status_code == 303
    assert plain.headers["location"] == "/login"
