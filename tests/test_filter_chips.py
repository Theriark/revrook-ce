"""The filter chips of the clients list (THE-1061): one chip per search, filter or
band in use, each a link to the list without it, the files the page links for
them and the live region.

The query and file tests need no database. The page test needs PostgreSQL
(DATABASE_URL) and is skipped without it, as the other page tests are.
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
from app.ui.brand import ASSET_FILES, FILTER_CHIP_FILES, STATIC_DIR, asset_version
from app.ui.clientlist import (
    BAND_CHOICES,
    BAND_WORDS,
    ActiveFilter,
    ListQuery,
)
from html_structure import structure_problems
from ui_helpers import NAME, seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
LIST = (ROOT / "app/ui/templates/clients.html").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "js/filter-chips.js").read_text(encoding="utf-8")
CSS = (STATIC_DIR / "css/filter-chips.css").read_text(encoding="utf-8")
VERSION = asset_version(files=FILTER_CHIP_FILES)
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
DIGEST = re.compile(r"[0-9a-f]{12}")
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FONT_SIZE = re.compile(r"(?<![-\w])font-size:\s*([^;]+);")
CHIP = re.compile(
    r'<a class="rv-chip rv-chip-remove" href="([^"]*)" data-filter-chip '
    r'data-filter-text="([^"]*)">'
)


# --- the query ----------------------------------------------------------------------


def test_no_chip_without_a_search_a_filter_or_a_band() -> None:
    assert ListQuery().active_filters == ()
    # The sort, the order, the density and the page arrange; they narrow nothing.
    arranged = ListQuery(sort="score", order="desc", density="compact", page=3)
    assert arranged.active_filters == ()


def test_each_chip_names_its_filter_and_links_to_the_list_without_it() -> None:
    query = ListQuery(q="Alder", show="needs-work", sort="score", page=2, band="none")
    assert query.active_filters == (
        ActiveFilter("q", 'Name contains "Alder"', "?show=needs-work&sort=score&band=none"),
        ActiveFilter("show", "Needs work", "?q=Alder&sort=score&band=none"),
        ActiveFilter("band", "Band: No report yet", "?q=Alder&show=needs-work&sort=score"),
    )
    # Every band the list accepts has its words.
    assert set(BAND_CHOICES) <= set(BAND_WORDS)
    for key in BAND_CHOICES:
        (chip,) = ListQuery(band=key).active_filters
        assert chip.text == f"Band: {BAND_WORDS[key]}" and chip.params == ""


def test_clear_all_keeps_the_arrangement_and_drops_every_filter() -> None:
    query = ListQuery(
        q="a", show="no-report", sort="evidence", order="desc", density="compact"
    )
    assert query.without_filters == "?sort=evidence&order=desc&density=compact"
    assert ListQuery(q="a", page=4).without_filters == ""


# --- the files ----------------------------------------------------------------------


def test_the_files_of_the_chips_have_their_own_version(tmp_path: Path) -> None:
    assert DIGEST.fullmatch(VERSION)
    assert templates.env.globals["filter_chips_version"] == VERSION
    # The shell's own digest is still that of ASSET_FILES alone.
    assert asset_version() == asset_version(files=ASSET_FILES)
    assert not set(FILTER_CHIP_FILES) & set(ASSET_FILES)
    copy = tmp_path / "static"
    for name in FILTER_CHIP_FILES:
        assert (STATIC_DIR / name).is_file(), name
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((STATIC_DIR / name).read_bytes())
    assert asset_version(copy, FILTER_CHIP_FILES) == VERSION
    (copy / "js/filter-chips.js").write_text("// changed", encoding="utf-8")
    assert asset_version(copy, FILTER_CHIP_FILES) != VERSION


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/static/js/filter-chips.js", "javascript"),
        ("/static/css/filter-chips.css", "text/css"),
    ],
)
async def test_the_files_of_the_chips_are_served_under_the_strict_policy(
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


def test_the_script_is_plain_and_hands_on_focus_and_words() -> None:
    assert '"use strict"' in SCRIPT
    for forbidden in (
        "eval(",
        "new Function",
        "innerHTML",
        "document.write",
        "http",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in SCRIPT, forbidden
    for needed in (
        '"Delete"',
        '"Backspace"',
        "window.sessionStorage",
        "MAX_AGE_MS",
        'getElementById("filter-status")',
        '"data-shown"',
        "target.focus()",
        "status.textContent",
        'ul[aria-label="Show"] a[aria-current="true"]',
    ):
        assert needed in SCRIPT, needed


def test_the_stylesheet_uses_tokens_and_respects_reduced_motion() -> None:
    assert HEX_LITERAL.search(CSS) is None
    assert "url(" not in CSS and "@import" not in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert set(FONT_SIZE.findall(CSS)) <= {"13px", "14px"}
    assert "flex: 1 1 100%;" in CSS
    assert "background-color: var(--rv-canvas);" in CSS


def test_the_template_links_the_files_and_keeps_the_live_region_apart() -> None:
    link = '<link rel="stylesheet" href="/static/css/filter-chips.css?v='
    assert link + '{{ filter_chips_version }}">' in LIST
    script = '<script src="/static/js/filter-chips.js?v='
    assert script + '{{ filter_chips_version }}" defer></script>' in LIST
    # The chips are in the toolbar; the live region follows the form, so it is on
    # the page whether or not a chip is left.
    chips = LIST.index('id="filters-active"')
    assert chips < LIST.index("</form>") < LIST.index('id="filter-status"')
    assert 'role="status" aria-live="polite"' in LIST
    assert '<span class="rv-sr-only">Remove filter: </span>' in LIST


# --- the page (PostgreSQL) ----------------------------------------------------------


async def test_the_list_draws_a_chip_for_each_filter_in_use(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    await seed_client(db_engine, ui_ctx)
    plain = await ui_browser.get("/clients")
    assert plain.status_code == 200 and structure_problems(plain.text) == []
    assert 'id="filters-active"' not in plain.text
    assert 'id="filter-status"' in plain.text
    assert 'data-shown="1 client shown."' in plain.text
    assert f'src="/static/js/filter-chips.js?v={VERSION}" defer' in plain.text
    assert f'href="/static/css/filter-chips.css?v={VERSION}"' in plain.text

    word = NAME.split()[0]
    params = {"q": word, "show": "no-report", "sort": "score"}
    narrowed = await ui_browser.get("/clients", params=params)
    html = narrowed.text
    assert narrowed.status_code == 200 and structure_problems(html) == []
    found = [(unescape(href), unescape(text)) for href, text in CHIP.findall(html)]
    assert found == [
        ("/clients?show=no-report&sort=score", f'Name contains "{word}"'),
        (f"/clients?q={word}&sort=score", "No report yet"),
    ]
    assert 'href="/clients?sort=score" data-filter-clear>Clear all filters</a>' in html
    assert 'data-shown="1 client shown."' in html

    nothing = await ui_browser.get("/clients", params={"q": "zzz"})
    assert nothing.status_code == 200 and structure_problems(nothing.text) == []
    assert len(CHIP.findall(nothing.text)) == 1
    assert "data-filter-clear" not in nothing.text
    assert 'data-shown="No client matches."' in nothing.text
