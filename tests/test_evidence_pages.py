"""The evidence page, the profile editor and the integrity check as rendered
(docs/design-system.md, Evidence imports, the profile editor and the integrity check).

The pages need PostgreSQL (DATABASE_URL) and are skipped without it. The editor's
posts are covered by tests/test_profile_editor.py; this file checks the parts of the
revamp: the verdict bands, the numbered refresh list, the tables that become cards,
the step cards of the editor and the empty states.
"""

import re
from types import SimpleNamespace

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evidence.service import EvidenceContext
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES
from helpers import VENDOR_COLUMNS, create_test_client, get_csrf, vendor_inventory
from html_structure import structure_problems
from ui_helpers import STATUS, STATUS_SPAN, seed_client, sign_in

EDITOR = "/imports/profile-editor"
INTEGRITY = "/evidence/integrity"
RECORDS = re.compile(r"<dt>Records</dt><dd>(\d+)</dd>")
VERDICT = re.compile(
    r"(The only chain is intact|All \d+ chains intact|\d+ of \d+ chains? broken)</span>"
)
# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32


async def test_the_evidence_page_has_its_verdict_the_refresh_list_and_the_tables(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get(f"/clients/{client_id}/evidence")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert html.count('aria-current="page"') == 2  # the rail and the tabs
    editor = f'href="/imports/profile-editor?client_id={client_id}">Import an export'
    assert f"{editor}</a>" in html
    assert '<section class="rv-verdict" id="evidence-status"' in html
    for fact in ("Sources", "Current", "To refresh", "Items imported"):
        assert f"<dt>{fact}</dt>" in html, fact
    # The backup export of the seeded client is 100 days old; the sources no
    # fixture covers were never imported, so the verdict is not protected.
    assert "1 expired, " in html and " not imported</span>" in html
    assert '<ol id="refresh-list">' in html
    assert '<span class="rv-refresh-when">newest export 2026-' in html
    assert '<span class="rv-refresh-how">' in html
    assert '<table id="sources" class="rv-table-cards rv-sources">' in html
    assert '<td data-label="Stale after" class="rv-date">' in html
    assert '<table id="items" class="rv-table-cards rv-items">' in html
    assert '<span class="rv-cell-note">Item ' in html
    assert '<td data-label="Size" class="rv-numeric">' in html and " bytes</td>" in html
    assert 'id="items-empty"' not in html
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))

    bare = await create_test_client(db_engine, ui_ctx, "Bare Client Ltd")
    page = await ui_browser.get(f"/clients/{bare}/evidence")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert "No evidence yet</span>" in html
    assert "<dt>Items imported</dt><dd>0</dd>" in html
    assert '<ol id="refresh-list">' in html  # every source is still to import
    assert 'id="items-empty"' in html and '<table id="items"' not in html
    assert ">Nothing imported yet</p>" in html


async def test_the_editor_is_five_step_cards_around_the_import_area(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    page = await ui_browser.get(EDITOR)
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert 'id="editor-empty"' in html and 'href="/clients">Add a client</a>' in html
    assert '<form id="rv-editor"' not in html

    client_id = await create_test_client(db_engine, ui_ctx)
    page = await ui_browser.get(EDITOR)
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert '<p class="rv-page-purpose">' in html
    assert html.count('<fieldset class="rv-step">') == 1
    assert '<label class="rv-dropzone">' in html
    assert 'id="file" name="file" type="file" accept=".csv,text/csv" required>' in html
    assert "at most 20 MB." in html
    assert 'id="rv-editor-busy" class="rv-editor-busy" aria-hidden="true">' in html
    assert 'id="rv-editor-hint"' in html and 'id="rv-import-result"' not in html

    csrf = await get_csrf(ui_browser, EDITOR)
    fields = {
        "csrf_token": csrf,
        "client_id": str(client_id),
        "source_code": "device-inventory",
    }
    for key, header in VENDOR_COLUMNS.items():
        fields[f"map-{key}"] = header
    files = {"file": ("vendor.csv", vendor_inventory(), "text/csv")}
    shown = await ui_browser.post(f"{EDITOR}/preview", data=fields, files=files)
    html = shown.text
    assert shown.status_code == 200, html
    assert structure_problems(html) == []
    assert html.count('<fieldset class="rv-step">') == 4
    assert '<h2 id="step-3-title" class="rv-step-title">' in html
    assert '<div class="rv-mapping">' in html and 'for="map-hostname"' in html
    assert 'id="rv-preview"' in html and 'id="rv-utc-note"' in html
    assert 'id="name-help" class="rv-help">' in html
    assert 'id="rv-no-profile"' in html and 'id="rv-busy-import"' not in html
    for name in ("preview", "save"):
        assert f'id="rv-busy-{name}" class="rv-editor-busy"' in html, name


async def test_the_integrity_page_starts_with_the_check_and_shows_its_verdict(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    page = await ui_browser.get(INTEGRITY)
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert 'id="integrity-start"' in html and ">Check all chains</button>" in html
    assert html.count('action="/evidence/integrity"') == 1
    assert ">Check again</button>" not in html and 'id="chains"' not in html

    # The evidence log is append-only and shared by the test run, so a check
    # through the app sees the chains of earlier tests; the page without any
    # record is rendered from the template with the context of an empty check.
    # The shell draws the rail (and the user's name in it) whenever `user` is
    # defined, so the render gets a stand-in user as the routes would supply.
    html = templates.get_template("evidence_integrity.html").render(
        title="Evidence integrity",
        nav="integrity",
        user=SimpleNamespace(username="admin"),
        brand_files=frozenset(BRAND_FILES),
        rows=[],
        failed=0,
        records=0,
        checked_at=None,
        csrf_token=PLACEHOLDER_TOKEN,
    )
    assert structure_problems(html) == []
    assert '<span class="rv-user-name">admin</span>' in html
    assert 'id="integrity-empty"' in html and ">Check again</button>" in html
    assert 'href="/imports/profile-editor">Open the profile editor</a>' in html
    assert 'id="integrity-start"' not in html and 'id="chains"' not in html

    await seed_client(db_engine, ui_ctx)
    csrf = await get_csrf(ui_browser, INTEGRITY)
    checked = await ui_browser.post(INTEGRITY, data={"csrf_token": csrf})
    html = checked.text
    assert checked.status_code == 200 and structure_problems(html) == []
    assert '<section class="rv-verdict" id="integrity-status"' in html
    assert VERDICT.search(html) is not None  # one pill, icon and words
    for fact in ("Chains checked", "Records", "Broken", "Checked"):
        assert f"<dt>{fact}</dt>" in html, fact
    records = RECORDS.search(html)
    assert records is not None and int(records.group(1)) >= 6  # six fixtures
    assert '<table id="chains" class="rv-table-cards rv-chains">' in html
    assert '<tr data-ok="true">' in html and '<code class="rv-hash">' in html
    assert '<td data-label="Problem"><span class="rv-text-secondary">None' in html
    assert html.count('action="/evidence/integrity"') == 1
    assert 'id="integrity-note"' in html and ">What the check proves</p>" in html
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
