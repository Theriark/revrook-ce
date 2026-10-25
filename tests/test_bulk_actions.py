"""The bulk actions of the clients list (THE-1189): the select boxes, the bar, the
dialog, the files the page links for them, and the two existing answers the script
relies on (a report made, a client deleted).

The file and template tests need no database. The page tests need PostgreSQL
(DATABASE_URL) and are skipped without it, as the other page tests are.
"""

import re
from html import unescape
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import make_engine
from app.evidence.service import EvidenceContext
from app.main import create_app
from app.settings import Settings
from app.ui.auth import templates
from app.ui.brand import (
    ASSET_FILES,
    BULK_ACTION_FILES,
    FILTER_CHIP_FILES,
    STATIC_DIR,
    asset_version,
)
from html_structure import structure_problems
from ui_helpers import NAME, seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
LIST = (ROOT / "app/ui/templates/clients.html").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "js/bulk-actions.js").read_text(encoding="utf-8")
CSS = (STATIC_DIR / "css/bulk-actions.css").read_text(encoding="utf-8")
VERSION = asset_version(files=BULK_ACTION_FILES)
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
ROW = re.compile(r'<tr data-bulk-row="(\d+)" data-name="([^"]*)"')
PICK = re.compile(
    r'<input type="checkbox" id="bulk-(\d+)" value="(\d+)" data-bulk-pick '
    r'aria-label="Select ([^"]*)">'
)


# --- the files ----------------------------------------------------------------------


def test_the_files_have_their_own_version() -> None:
    assert re.fullmatch(r"[0-9a-f]{12}", VERSION)
    assert templates.env.globals["bulk_actions_version"] == VERSION
    assert not set(BULK_ACTION_FILES) & set(ASSET_FILES)
    assert not set(BULK_ACTION_FILES) & set(FILTER_CHIP_FILES)
    for name in BULK_ACTION_FILES:
        assert (STATIC_DIR / name).is_file(), name


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/static/js/bulk-actions.js", "javascript"),
        ("/static/css/bulk-actions.css", "text/css"),
    ],
)
async def test_the_files_are_served_under_the_strict_policy(
    settings: Settings, path: str, media_type: str
) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert media_type in response.headers["content-type"]
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy


def test_the_script_builds_no_markup_and_posts_only_to_existing_actions() -> None:
    assert '"use strict"' in SCRIPT
    for forbidden in (
        "eval(",
        "new Function",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "http:",
        "https:",
        "XMLHttpRequest",
        "localStorage",
    ):
        assert forbidden not in SCRIPT, forbidden
    # The two addresses it posts to, built from a row id that is digits only.
    paths = re.findall(r'post\("([^"]+)"', SCRIPT)
    assert paths == ["/clients/", "/system/clients/"]
    assert '"/reports/snapshot"' in SCRIPT and '"/delete"' in SCRIPT
    assert "/^[0-9]+$/.test(value)" in SCRIPT
    assert 'credentials: "same-origin"' in SCRIPT
    assert 'body.append("csrf_token", csrf)' in SCRIPT
    assert '"X-CSRF-Token": csrf' in SCRIPT
    # A deletion counts only where the System page says so; the sign-in page is
    # an ended session, never a success.
    assert 'landed.searchParams.get("deleted") === "1"' in SCRIPT
    assert SCRIPT.count('=== "/login"') == 2
    # Words go in as text, and the dialog never runs a stale choice on Escape.
    assert ".textContent" in SCRIPT and 'dialog.returnValue = "";' in SCRIPT
    assert "var MAX_DELETE = 10;" in SCRIPT
    assert 'input.value.trim() === input.getAttribute("data-name")' in SCRIPT
    # A spreadsheet reads a cell that starts like a formula as text.
    assert "/^[=+\\-@\\t\\r]/" in SCRIPT


def test_the_stylesheet_uses_tokens_and_respects_reduced_motion() -> None:
    plain = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
    assert "#" not in plain
    for forbidden in ("url(", "@import", "http"):
        assert forbidden not in plain, forbidden
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "position: sticky;" in CSS and "@media (max-width: 1023px)" in CSS
    sizes = set(re.findall(r"(?<![-\w])font-size:\s*([^;]+);", plain))
    assert sizes <= {"13px", "14px"}, sizes


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_every_text_rule_of_the_bulk_actions_reaches_its_contrast(theme: str) -> None:
    from test_brand_contrast import THEMES, contrast_ratio, parse_rules, resolve

    variables = THEMES[theme]
    checked = 0
    for selector, declarations in parse_rules(CSS):
        if "color" not in declarations:
            continue
        assert "background-color" in declarations, selector
        text = resolve(declarations["color"], variables)
        background = resolve(declarations["background-color"], variables)
        assert text and background, selector
        ratio = contrast_ratio(text, background)
        assert ratio >= 4.5, f"{selector} ({theme}): {ratio:.2f}"
        checked += 1
    assert checked >= 6


# --- the template -------------------------------------------------------------------


def test_the_selection_is_hidden_until_the_script_reveals_it() -> None:
    link = '<link rel="stylesheet" href="/static/css/bulk-actions.css?v='
    assert link + '{{ bulk_actions_version }}">' in LIST
    script = '<script src="/static/js/bulk-actions.js?v='
    assert script + '{{ bulk_actions_version }}" defer></script>' in LIST
    assert '<div class="rv-bulk-select" id="bulk-select" hidden>' in LIST
    assert LIST.count("data-bulk-cell hidden") == 2
    assert 'id="bulk-bar" role="region" aria-labelledby="bulk-count" hidden' in LIST
    # Every column of a card still has its name; the select box has its label.
    assert LIST.count('data-label="') == 5
    assert 'aria-label="Select {{ row.name }}"' in LIST
    assert "Select every client on this page" in LIST
    assert 'data-csrf="{{ csrf_token }}"' in LIST


def test_the_bar_offers_the_actions_and_the_dialog_asks_first() -> None:
    bar = LIST.split('id="bulk-bar"', 1)[1].split("</div>\n</div>", 1)[0]
    for action in ("report", "csv", "delete", "clear"):
        assert f'data-bulk-action="{action}"' in bar, action
    assert 'class="rv-button-danger rv-button-small" data-bulk-action="delete"' in bar
    assert 'id="bulk-result" role="status" aria-live="polite"' in LIST
    dialog = LIST.split('<dialog class="rv-dialog rv-bulk-dialog"', 1)[1]
    dialog = dialog.split("</dialog>", 1)[0]
    assert 'aria-labelledby="bulk-dialog-title"' in dialog
    assert '<form method="dialog"' in dialog
    assert 'value="cancel" data-bulk-cancel>Cancel</button>' in dialog
    assert 'value="confirm" data-bulk-confirm>' in dialog
    for part in ("data-name=", "data-score=", "data-band=", "data-newest="):
        assert part in LIST, part


# --- the page and the answers the script relies on (PostgreSQL) -------------------


async def test_the_list_draws_a_select_box_for_every_row(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    token = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    hostile = '<b id="main">Finch</b>'
    other = await seed_client(db_engine, ui_ctx, hostile)
    page = await ui_browser.get("/clients")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert f'src="/static/js/bulk-actions.js?v={VERSION}" defer' in html
    assert f'href="/static/css/bulk-actions.css?v={VERSION}"' in html
    rows = {int(found): unescape(name) for found, name in ROW.findall(html)}
    assert rows == {client_id: NAME, other: hostile}
    picks = PICK.findall(html)
    assert sorted(int(found) for found, _, _ in picks) == sorted(rows)
    assert all(found == value for found, value, _ in picks)
    assert '<b id="main">' not in html
    assert f'data-csrf="{token}"' in html


async def test_the_list_without_clients_has_no_selection(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await sign_in(ui_browser, db_engine)
    page = await ui_browser.get("/clients")
    assert page.status_code == 200 and structure_problems(page.text) == []
    assert 'id="clients-empty"' in page.text
    assert 'id="bulk-bar"' not in page.text and 'id="bulk-select"' not in page.text


async def test_the_answers_the_script_reads_for_a_report_and_a_deletion(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    token = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    # A report without dates: a redirect to the report the script links to.
    made = await ui_browser.post(
        f"/clients/{client_id}/reports/snapshot",
        data={"csrf_token": token},
        headers={"X-CSRF-Token": token},
    )
    assert made.status_code == 303
    assert re.fullmatch(rf"/clients/{client_id}/reports/\d+", made.headers["location"])
    # A wrong name: the problem page with its message, and nothing deleted.
    refused = await ui_browser.post(
        f"/system/clients/{client_id}/delete",
        data={"csrf_token": token, "confirm": "Not the name"},
    )
    assert refused.status_code >= 400
    assert 'class="rv-problem-message"' in refused.text
    assert "Nothing was deleted" in refused.text
    still = await ui_browser.get("/clients")
    assert f'data-bulk-row="{client_id}"' in still.text
    # The exact name: the redirect the script checks for, and the row is gone.
    deleted = await ui_browser.post(
        f"/system/clients/{client_id}/delete",
        data={"csrf_token": token, "confirm": NAME},
    )
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/system?deleted=1"
    gone = await ui_browser.get("/clients")
    assert f'data-bulk-row="{client_id}"' not in gone.text
