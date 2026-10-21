"""The follow-up of the web UI retest (THE-520, REV-137).

Seen on Development after the corrections of THE-505: at 768px the client tabs
showed a fade with every tab in view and the cut link of the navigation got only a
faint cue; adding or closing an exception and saving the details of a report gave
no message after the redirect; the export history and the schedules broke a file
name, a SHA-256 or a cron expression into columns of six letters at 768px; the
summary of an opened delete disclosure was grey on charcoal at 390px. From the code
review: an address no page answers gave a 500 when the database was down, a link
that keyboard focus scrolled into view could land under the fade, and `/api`
without a slash got the problem page instead of JSON.

The rules of the follow-up are in app/static/css/revrook-retest.css, loaded after
revrook.css, which is unchanged. The page tests need PostgreSQL (DATABASE_URL) and
are skipped without it.
"""

import logging
import re
from datetime import timedelta
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from test_brand_contrast import BODY_MINIMUM, LARGE_MINIMUM, VARIABLES, contrast_ratio

from app.db import make_engine
from app.evidence.service import EvidenceContext
from app.main import create_app, is_page_address
from app.models import AuditEvent
from app.security import SESSION_COOKIE
from app.settings import Settings
from app.ui.auth import templates
from app.ui.brand import ASSET_FILES, BRAND_FILES
from app.ui.clients import EXCEPTION_DONE
from app.ui.dashboard import (
    DELETED_CLIENT,
    LABEL_GAP,
    ReportPoint,
    change_lines,
    deleted_client_name,
    trend_chart,
)
from app.ui.profiles import PAGE_TEMPLATE, RESULT_TEMPLATE
from app.ui.reports import DETAILS_SAVED
from helpers import NOW
from html_structure import structure_problems
from tools.score_inputs import AS_OF
from ui_helpers import seed_client, sign_in

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app/static"
TEMPLATES = ROOT / "app/ui/templates"
CSS = (STATIC / "css/revrook.css").read_text(encoding="utf-8")
FOLLOW_UP = (STATIC / "css/revrook-retest.css").read_text(encoding="utf-8")
SCRIPT = (STATIC / "js/revrook.js").read_text(encoding="utf-8")
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
STYLESHEET = 'href="/static/css/revrook.css?v={{ asset_version }}"'
FOLLOW_UP_LINK = 'href="/static/css/revrook-retest.css?v={{ asset_version }}"'
CONTROL = "PC-ACC-01"
# A PostgreSQL address nothing listens on (tests/test_health.py uses the same).
UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"


def rule(selector: str, css: str = FOLLOW_UP) -> str:
    """The declarations of the (last) rule with exactly this selector."""
    found = re.findall(rf"\n{re.escape(selector)} \{{([^}}]*)\}}", css)
    assert found, selector
    return found[-1]


def without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def media_blocks(until: int, css: str = FOLLOW_UP) -> list[str]:
    """The bodies of the blocks from 768px up to this width."""
    query = rf"@media \(min-width: 768px\) and \(max-width: {until}px\) "
    return re.findall(query + r"\{(.*?)\n\}\n", css, re.DOTALL)


# --- the follow-up stylesheet -----------------------------------------------------


def test_the_follow_up_stylesheet_is_linked_after_the_main_one_and_versioned() -> None:
    assert "css/revrook-retest.css" in ASSET_FILES
    assert BASE.index(STYLESHEET) < BASE.index(FOLLOW_UP_LINK)
    # Like revrook.css: tokens only, no colour literal, no image, nothing external.
    rules = without_comments(FOLLOW_UP)
    assert "#" not in rules
    for forbidden in ("url(", "data:", "@import", "http"):
        assert forbidden not in rules, forbidden


# --- defect 5 at 768px: the cue of the scrolling strips -----------------------------


def test_the_strip_fade_is_steeper_as_wide_as_its_tail_and_scroll_aware() -> None:
    fade = "linear-gradient(to right, transparent, var(--rv-{}) 40%)"
    assert fade.format("charcoal") in rule(".rv-nav-strip::after")
    assert fade.format("white") in rule(".rv-tabs-strip::after")
    # revrook.css keeps the 48px fade that takes no pointer; only its stop moved.
    assert "width: 48px;" in rule(".rv-nav-strip::after", CSS)
    assert "pointer-events: none;" in rule(".rv-tabs-strip::after", CSS)
    tail = rule(".rv-nav::after,\n.rv-tabs-strip > nav > ul::after")
    assert "width: 48px;" in tail
    hidden = rule(
        '.rv-nav-strip[data-scroll-end="true"]::after,\n'
        '.rv-tabs-strip[data-scroll-end="true"]::after'
    )
    assert "display: none;" in hidden
    # The script marks the strips; without it the stylesheet keeps the fade.
    assert 'document.querySelectorAll(".rv-nav-strip, .rv-tabs-strip")' in SCRIPT
    assert 'var links = scroller.querySelectorAll("a");' in SCRIPT
    assert "var last = links[links.length - 1].getBoundingClientRect();" in SCRIPT
    assert "var edge = box.left + scroller.clientLeft + scroller.clientWidth;" in (
        SCRIPT
    )
    assert "atEnd = last.right <= edge + 1;" in SCRIPT
    assert 'strip.setAttribute("data-scroll-end", atEnd ? "true" : "false");' in (
        SCRIPT
    )
    for event in ('"scroll", update', '"resize", update', '"load", update'):
        assert event in SCRIPT, event
    unwanted = ("eval(", "fetch(", "XMLHttpRequest", "innerHTML", "document.write")
    for forbidden in unwanted:
        assert forbidden not in SCRIPT, forbidden


# --- R1 (review of the follow-up): the end padding of the scroller counts -----------


def test_a_strip_is_at_its_end_only_past_the_end_padding_of_its_scroller() -> None:
    # The navigation bar keeps 16px of end padding after its 48px tail (revrook.css),
    # so its true end is 64px after the last link; with the tail alone the fade
    # stayed over the last link for the last 16px of scrolling. The tabs have none.
    assert "padding: 0 16px 4px;" in rule(".rv-header nav,\n.rv-nav", CSS)
    assert "padding" not in rule("main nav", CSS)
    assert "padding" not in rule(".rv-tabs-strip > nav", CSS)
    # F4 of the live retest (THE-524): the script measures the last link against
    # the visible box of the element that scrolls (the padding is inside that
    # box), so neither the tail nor the padding is a constant that can drift from
    # the stylesheet, and the 4px gap before the tail counts too (with the
    # constants the cue went 3px late at the client tabs).
    assert "STRIP_TAIL" not in SCRIPT
    assert "paddingRight" not in SCRIPT
    assert "var box = scroller.getBoundingClientRect();" in SCRIPT
    assert "var edge = box.left + scroller.clientLeft + scroller.clientWidth;" in (
        SCRIPT
    )
    assert "atEnd = last.right <= edge + 1;" in SCRIPT
    # A strip with no link at all counts as at its end: nothing to scroll to.
    assert "var atEnd = true;\n      if (links.length > 0) {" in SCRIPT


# --- R2 (review of the follow-up): the message after a redirect is read out ---------


def test_the_message_after_a_redirect_is_focused_and_its_query_cleared() -> None:
    exceptions = (TEMPLATES / "exceptions.html").read_text(encoding="utf-8")
    reports = (TEMPLATES / "reports.html").read_text(encoding="utf-8")
    assert (
        'role="status" id="exceptions-message" tabindex="-1" data-clear-query="done"'
        in exceptions
    )
    assert (
        'role="status" id="builder-message" tabindex="-1" data-clear-query="saved"'
        in reports
    )
    # The script moves focus to the message (a status region already on the page
    # when it loads is often not read out) and takes the named query off the
    # address in place, so a reload does not repeat the message. Without the
    # script the redirect and the message are as before: the server draws them.
    assert 'document.querySelectorAll("[data-clear-query]")' in SCRIPT
    assert 'var name = message.getAttribute("data-clear-query");' in SCRIPT
    assert "message.focus();" in SCRIPT
    assert "address.searchParams.delete(name);" in SCRIPT
    assert (
        'window.history.replaceState(window.history.state, "", address.href);' in SCRIPT
    )


# --- defect 10: a message that survives the redirect --------------------------------


async def test_adding_and_closing_an_exception_and_saving_details_say_so(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    base = f"/clients/{client_id}/exceptions"
    review = (NOW.date() + timedelta(days=90)).isoformat()
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
    assert added.headers["location"] == f"{base}?done=added"
    listing = await ui_browser.get(added.headers["location"])
    assert listing.status_code == 200
    assert 'id="exceptions-message"' in listing.text
    assert 'id="exceptions-message" tabindex="-1" data-clear-query="done"' in (
        listing.text
    )
    assert EXCEPTION_DONE["added"] in listing.text
    assert structure_problems(listing.text) == []
    found = re.search(rf"{base}/(\d+)/close", listing.text)
    assert found is not None
    closed = await ui_browser.post(
        f"{base}/{found.group(1)}/close", data={"csrf_token": csrf}
    )
    assert closed.status_code == 303
    assert closed.headers["location"] == f"{base}?done=closed"
    after = await ui_browser.get(closed.headers["location"])
    assert EXCEPTION_DONE["closed"] in after.text
    # The plain page, or an unknown word, shows no message; a 422 shows the errors.
    for query in ("", "?done=nope"):
        plain = await ui_browser.get(f"{base}{query}")
        assert plain.status_code == 200 and 'id="exceptions-message"' not in plain.text
    # The details of a report, posted without script, come back with a message too.
    builder = f"/clients/{client_id}/reports"
    saved = await ui_browser.post(
        f"{builder}/details", data={"csrf_token": csrf, "plan": "A line"}
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == f"{builder}?saved=1"
    page = await ui_browser.get(saved.headers["location"])
    assert page.status_code == 200
    assert 'id="builder-message"' in page.text and DETAILS_SAVED in page.text
    assert 'id="builder-message" tabindex="-1" data-clear-query="saved"' in page.text
    assert structure_problems(page.text) == []
    assert 'id="builder-message"' not in (await ui_browser.get(builder)).text
    # With script the form still gets the "Saved at" fragment in place.
    fragment = await ui_browser.post(
        f"{builder}/details",
        data={"plan": "A line"},
        headers={"HX-Request": "true", "X-CSRF-Token": csrf},
    )
    assert fragment.status_code == 200 and "Saved at" in fragment.text


# --- defect 11: hash, file and cron cells at 768px ----------------------------------


def test_the_export_history_and_the_schedules_are_cards_below_the_sidebar() -> None:
    # The export history fits as a table beside the sidebar, so its cards end at
    # 1023px; the schedules have their own block, to 1099px (the live retest).
    narrow = media_blocks(1023)
    assert len(narrow) == 1
    cards = narrow[0]
    assert re.search(r"main table\.rv-exports,\n(.*\n)*?    display: block;", cards)
    assert "content: attr(data-label);" in cards
    assert "main .rv-exports td[data-label]::before {" in cards
    assert "main .rv-exports td:empty {\n    display: none;" in cards
    assert "\n  .rv-exports thead th {\n    position: static;" in cards
    # An export is one card a row (a digest keeps one line); schedules two a row.
    assert "display: grid;" not in cards
    assert "rv-schedules" not in cards
    wide = media_blocks(1099)
    assert len(wide) == 1
    grid = wide[0]
    assert re.search(r"main table\.rv-schedules,\n(.*\n)*?    display: block;", grid)
    assert "content: attr(data-label);" in grid
    assert "main .rv-schedules td[data-label]::before {" in grid
    assert "main .rv-schedules td:empty {\n    display: none;" in grid
    assert "\n  .rv-schedules thead th {\n    position: static;" in grid
    assert re.search(
        r"\.rv-schedules tbody \{\n    display: grid;\n"
        r"    grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);",
        grid,
    )
    assert (
        "grid-template-columns: repeat(2, minmax(0, 1fr));"
        not in grid.split(".rv-schedules tbody {")[0]
    )
    assert "main .rv-schedules tbody tr {\n    margin-bottom: 0;" in grid
    assert "rv-exports" not in grid
    assert "white-space: nowrap;" in rule(".rv-schedules code")
    # The tables carry the classes the rules address, and a cron is a code element.
    exports = (TEMPLATES / "exports.html").read_text(encoding="utf-8")
    system = (TEMPLATES / "system.html").read_text(encoding="utf-8")
    assert 'class="rv-table-cards rv-exports"' in exports
    assert '<td data-label="SHA-256"><code class="rv-digest">' in exports
    assert 'class="rv-table-cards rv-schedules"' in system
    assert '<td data-label="When"><code>{{ line.cron }}</code></td>' in system


# --- defect 12: the opened delete disclosure at 390px -------------------------------


def test_an_opened_delete_disclosure_is_white_on_charcoal() -> None:
    open_summary = rule(
        "details.rv-confirm[open] > summary,\n"
        "details.rv-confirm[open] > summary:focus,\n"
        "details.rv-confirm[open] > summary:not([role]):not(:focus)"
    )
    assert "color: var(--rv-white);" in open_summary
    assert "background-color: var(--rv-charcoal);" in open_summary
    white, charcoal = VARIABLES["--rv-white"], VARIABLES["--rv-charcoal"]
    assert contrast_ratio(white, charcoal) >= BODY_MINIMUM
    # The grey Pico used (the muted colour) fails on charcoal, so the rule is needed.
    grey = VARIABLES["--rv-text-secondary"]
    assert contrast_ratio(grey, charcoal) < BODY_MINIMUM
    # The closed summary and its hover are unchanged in revrook.css.
    assert "color: var(--rv-charcoal);" in rule("details.rv-confirm > summary", CSS)
    assert "color: var(--rv-white);" in rule("details.rv-confirm > summary:hover", CSS)
    system = (TEMPLATES / "system.html").read_text(encoding="utf-8")
    assert '<details class="rv-confirm">\n<summary>Delete {{ client.name }}' in system


# --- L1: an unknown address with the database down ----------------------------------


async def test_an_unknown_address_is_the_problem_page_with_the_database_down(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A signed-in session cookie makes the page ask the database who is signed in.
    await sign_in(ui_browser, db_engine)
    cookie = ui_browser.cookies.get(SESSION_COOKIE)
    assert cookie
    caplog.set_level(logging.WARNING, logger="revrook.web")
    down = create_app(ui_settings, engine=make_engine(UNREACHABLE))
    transport = httpx.ASGITransport(app=down)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies={SESSION_COOKIE: cookie}
    ) as client:
        missing = await client.get("/no-such-page")
        wrong = await client.post("/glossary", data={"csrf_token": "x"})
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("text/html")
    assert "There is no page at this address." in missing.text
    # Drawn in the signed-out shell: no navigation, no user, nothing of the data.
    assert 'class="rv-problem"' in missing.text
    assert 'class="rv-nav"' not in missing.text
    assert structure_problems(missing.text) == []
    assert wrong.status_code == 405 and "GET" in wrong.headers["allow"]
    assert 'class="rv-nav"' not in wrong.text
    # R3 (review of the follow-up): the outage leaves one warning a request, naming
    # the class of the error and nothing of the statement or the address.
    warnings = [r for r in caplog.records if r.name == "revrook.web"]
    assert len(warnings) == 2
    for record in warnings:
        assert record.levelno == logging.WARNING
        assert re.fullmatch(
            r"The problem page could not read who is signed in: \w+",
            record.getMessage(),
        )
        assert "unused" not in record.getMessage()  # the password of UNREACHABLE


# --- L2: a focused link is never under the fade -------------------------------------


def test_keyboard_focus_scrolls_a_link_clear_of_the_fade() -> None:
    padded = rule(".rv-header nav,\n.rv-nav,\n.rv-tabs-strip > nav")
    assert "scroll-padding-right: 48px;" in padded
    # The padding equals the fade, which takes no pointer; the strips scroll in
    # these very elements (revrook.css).
    assert "width: 48px;" in rule(".rv-nav-strip::after", CSS)
    assert "pointer-events: none;" in rule(".rv-nav-strip::after", CSS)
    assert "overflow-x: auto;" in rule(".rv-header nav,\n.rv-nav", CSS)
    assert "overflow-x: auto;" in rule("main nav", CSS)
    assert '<div class="rv-tabs-strip">\n<nav class="rv-client-nav"' in (
        TEMPLATES / "_client_nav.html"
    ).read_text(encoding="utf-8")


# --- L3: the API, the probes and the static files keep JSON, /api included ----------


@pytest.mark.parametrize(
    ("path", "page"),
    [
        ("/api", False),
        ("/api/", False),
        ("/api/v1/no-such", False),
        ("/healthz", False),
        ("/readyz", False),
        ("/metrics", False),
        ("/static/css/no-such.css", False),
        ("/", True),
        ("/apiary", True),
        ("/no-such-page", True),
        ("/clients/1/no-such", True),
    ],
)
def test_which_addresses_get_the_problem_page(path: str, page: bool) -> None:
    assert is_page_address(path) is page


async def test_the_api_and_the_probes_refuse_in_json_for_any_method(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await sign_in(ui_browser, db_engine)
    for path in ("/api", "/api/", "/api/v1", "/api/v1/no-such"):
        missing = await ui_browser.get(path)
        assert missing.status_code == 404, path
        assert missing.headers["content-type"].startswith("application/json"), path
        assert missing.json() == {"detail": "Not Found"}, path
    # A method an API path or a probe does not take: JSON too, with Allow kept.
    for path in ("/api/v1/whoami", "/healthz", "/readyz"):
        wrong = await ui_browser.post(path, data={"csrf_token": "x"})
        assert wrong.status_code == 405, path
        assert wrong.headers["content-type"].startswith("application/json"), path
        assert "GET" in wrong.headers["allow"], path
        assert wrong.json() == {"detail": "Method Not Allowed"}, path
    # An address that merely starts with the letters of the prefix is a page.
    page = await ui_browser.get("/apiary")
    assert page.status_code == 404
    assert page.headers["content-type"].startswith("text/html")
    assert 'class="rv-problem"' in page.text


# --- D1: the counts of an import at 390px -------------------------------------------


def test_the_counts_of_an_import_scroll_inside_their_card() -> None:
    result = (TEMPLATES / "_profile_editor_result.html").read_text(encoding="utf-8")
    region = (
        '<div class="rv-table-scroll" role="region" '
        'aria-label="What the import counted" tabindex="0">\n'
        '<table id="rv-import-summary">'
    )
    assert region in result
    assert "</table>\n</div>\n{% endif %}\n<h3" in result
    assert "overflow-x: auto;" in rule(".rv-table-scroll", CSS)
    assert "overflow-wrap: anywhere;" in rule(".rv-import-result .rv-table-scroll th")
    imported = SimpleNamespace(
        item_id=5,
        profile_id=4,
        facts=3,
        summary=[("a_very_long_count_name_nobody_would_break", 1)],
        controls=[],
        control_total=51,
    )
    context: dict[str, object] = {
        "errors": [],
        "saved": None,
        "imported": imported,
        "preview": None,
        "profiles": [],
        "profile_id": None,
        "name": "",
        "client_id": None,
        "csrf_token": "x" * 32,
        "brand_files": frozenset(BRAND_FILES),
    }
    html = templates.get_template(RESULT_TEMPLATE).render(context)
    assert 'aria-label="What the import counted"' in html
    assert "a_very_long_count_name_nobody_would_break" in html


# --- D2: the checklist at 768px -----------------------------------------------------


def test_the_checklist_fits_between_768_and_1079px() -> None:
    # Six columns need 747px; the page gives 720px at 768px and 712px beside the
    # sidebar at 1024px (the live retest), so the padding is reduced to 1079px:
    # 6px a side (the review of that fix: with a classic 15px scrollbar the page
    # is 697px at 1024px, and 8px cells, 699px, overflowed it by 2px).
    checklist = [block for block in media_blocks(1079) if "rv-checklist" in block]
    assert len(checklist) == 1
    assert re.search(
        r"main \.rv-checklist th,\n  main \.rv-checklist td \{\n"
        r"    padding-right: 6px;\n    padding-left: 6px;",
        checklist[0],
    )
    assert re.search(
        r"\.rv-checklist \.rv-coverage \{\n    white-space: normal;", checklist[0]
    )
    assert "rv-checklist" not in "".join(media_blocks(1023))
    # The sticky head and the cards below 768px of revrook.css stay as they are.
    assert "white-space: nowrap;" in rule(".rv-coverage", CSS)
    assert re.search(r"\n  main table\.rv-checklist,\n  \.rv-checklist tbody,", CSS)


# --- D3: the entries of a deleted client on Home ------------------------------------


def test_the_entries_of_a_deleted_client_are_told_apart_by_its_number() -> None:
    # The name itself is gone with the client (deletion removes every row of it
    # and the audit trail keeps counts only), so the number names the client.
    when = NOW - timedelta(minutes=5)
    events = [
        AuditEvent(
            occurred_at=when,
            actor_user_id=1,
            action="evidence.added",
            target_type=None,
            target_id=None,
            detail={"client_id": 7, "source_code": "x"},
        ),
        AuditEvent(
            occurred_at=when,
            actor_user_id=None,
            action="client.deleted",
            target_type="client",
            target_id="9",
            detail={"items": 2},
        ),
    ]
    lines = change_lines(events, {3: "Still here Ltd"}, {1: "admin"}, NOW)
    assert lines[0].client_name == "a deleted client (client 7)"
    assert lines[1].client_name == "a deleted client (client 9)"
    assert lines[0].client_name != lines[1].client_name
    assert lines[0].href == "" and lines[1].href == ""
    assert deleted_client_name(7).startswith(DELETED_CLIENT)
    # The template writes "<words> for <client>", so the entry reads as a sentence.
    home = (TEMPLATES / "home.html").read_text(encoding="utf-8")
    assert "{{ line.words }}{% if line.client_name %} for " in home


# --- D4: the labels at the ends of the trend lines ----------------------------------


def test_stacked_trend_labels_keep_air_between_them() -> None:
    # A label is 12 units of text in a box of about 14 (measured at 768px: the
    # first ended where the next began), so the stack needs more than 14.
    assert LABEL_GAP >= 18
    assert "font-size: 12px;" in rule(".rv-chart", CSS)
    names = {1: "Alder Ltd", 2: "Birch Ltd", 3: "Cedar Ltd"}
    same = [ReportPoint(k, AS_OF, Fraction(70), "Good", False, 40, 5) for k in names]
    chart = trend_chart(same, names, AS_OF + timedelta(hours=1))
    places = sorted(float(line.label_y) for line in chart.lines)
    for upper, lower in pairwise(places):
        assert lower - upper >= LABEL_GAP
    # Six labels still fit in the plot above the dates of the axis.
    many = {k: f"Client {k}" for k in range(1, 7)}
    floor = [ReportPoint(k, AS_OF, Fraction(0), "Poor", False, 40, 5) for k in many]
    stacked = trend_chart(floor, many, AS_OF + timedelta(hours=1))
    lowest = max(float(line.label_y) for line in stacked.lines)
    assert lowest <= stacked.bottom - LABEL_GAP / 2
    assert min(float(line.label_y) for line in stacked.lines) >= stacked.top


# --- F1 (live retest THE-524): the exceptions register from 768px to 1279px --------


def test_the_exceptions_register_never_widens_the_page() -> None:
    exceptions = (TEMPLATES / "exceptions.html").read_text(encoding="utf-8")
    region = (
        '<div class="rv-table-scroll rv-exceptions-scroll" role="region" '
        'aria-label="Exceptions register" tabindex="0">\n'
        '<table id="exceptions" class="rv-table-cards rv-exceptions">'
    )
    assert region in exceptions
    assert "</tbody>\n</table>\n</div>\n{% else %}" in exceptions
    assert "overflow-x: auto;" in rule(".rv-table-scroll", CSS)
    # Seven columns need 804px; the page gives 704px at 768px and 712px beside
    # the sidebar at 1024px, so the rows are cards until 1280px (968px of page).
    cards = [b for b in media_blocks(1279) if "main table.rv-exceptions," in b]
    assert len(cards) == 1
    assert re.search(
        r"main table\.rv-exceptions,\n(.*\n)*?    display: block;", cards[0]
    )
    assert "content: attr(data-label);" in cards[0]
    assert "main .rv-exceptions td[data-label]::before {" in cards[0]
    assert "main .rv-exceptions td:empty {\n    display: none;" in cards[0]
    assert "\n  .rv-exceptions thead th {\n    position: static;" in cards[0]
    # One card a row (the reason and the compensating control are prose), and a
    # card cell is not capped at the 20rem of a column in a scrolling table.
    assert "display: grid;" not in cards[0]
    assert "max-width: none;" in rule("main .rv-exceptions-scroll td")
    assert "max-width: 24rem;" in rule(".rv-exceptions .rv-exception-text", CSS)
    # Below 768px the cards of revrook.css take over; the thead is the sticky
    # one of revrook.css only when the rows are a table.
    assert re.search(r"\n  main table\.rv-table-cards,\n  \.rv-table-cards tbody,", CSS)
    assert "position: sticky;" in rule("main table thead th", CSS)
    # Every cell of a row names its column, so a card reads whole.
    for label in ("Owner", "Reason", "Compensating control", "Review date", "State"):
        assert f'<td data-label="{label}"' in exceptions, label


# --- After the deploy of F1: the other wide tables beside the sidebar ---------------

# Measured on Development after the deploy of F1, in the sweep of every page at
# 320, 390, 768, 769, 800, 1024 and 1440px: from 1024px the page is 312px
# narrower than the window (712px at 1024px, with the sidebar), and two tables
# that fit from 768px to 1023px pushed the page sideways there: the schedules by
# 24px and the checklist by 3px. The width of each table at its narrowest is a
# measurement; the window the sidebar appears at, the width of the sidebar, the
# gutters of the page and the last window width of each block are read from the
# stylesheets (the review of that fix asked that no breakpoint be copied). A
# classic scrollbar (Windows, or Linux without overlay scrollbars) takes 15px
# off the page, and every block leaves it that room.
WIDE_TABLES = {"rv-schedules": 768, "rv-exceptions": 804}
CHECKLIST = 747
CLASSIC_SCROLLBAR = 15


def shell_geometry() -> tuple[int, int, int]:
    """The window the sidebar appears at, its width and the gutter of the page."""
    sidebar = re.search(
        r"@media \(min-width: (\d+)px\) \{\n  body\.rv-app \{\n"
        r"    grid-template-columns: (\d+)px minmax",
        CSS,
    )
    gutter = re.search(
        r"@media \(min-width: 768px\) \{\n  \.rv-content \{\n"
        r"    padding: \d+px (\d+)px \d+px;",
        CSS,
    )
    assert sidebar is not None and gutter is not None
    return int(sidebar.group(1)), int(sidebar.group(2)), int(gutter.group(1))


def page_width(window: int) -> int:
    """The width of the page at this window width, from 768px up."""
    sidebar_window, sidebar, gutter = shell_geometry()
    beside = sidebar if window >= sidebar_window else 0
    return window - beside - 2 * gutter


def block_end(marker: str, css: str = FOLLOW_UP) -> int:
    """The last window width of the 768px-and-up block that holds this text."""
    blocks = re.findall(
        r"@media \(min-width: 768px\) and \(max-width: (\d+)px\) \{(.*?)\n\}\n",
        css,
        re.DOTALL,
    )
    found = [int(until) for until, body in blocks if marker in body]
    assert len(found) == 1, marker
    return found[0]


def test_the_shell_geometry_is_read_from_the_stylesheet() -> None:
    assert shell_geometry() == (1024, 248, 32)
    # The measured page widths of the live retest: 704px at 768px, 712px beside
    # the sidebar at 1024px, 968px at 1280px.
    assert (page_width(768), page_width(1024), page_width(1280)) == (704, 712, 968)


def test_the_wide_tables_are_cards_until_the_page_beside_the_sidebar_fits() -> None:
    for table, width in WIDE_TABLES.items():
        until = block_end(f"main table.{table},")
        block = [b for b in media_blocks(until) if f"main table.{table}," in b]
        assert len(block) == 1, table
        assert "display: block;" in block[0], table
        # The first window of the table has a page that holds it beside a
        # classic scrollbar.
        assert page_width(until + 1) - CLASSIC_SCROLLBAR >= width, table
    until = block_end("main .rv-checklist th,")
    padded = [b for b in media_blocks(until) if "main .rv-checklist th," in b]
    assert len(padded) == 1 and "padding-left: 6px;" in padded[0]
    assert page_width(until + 1) - CLASSIC_SCROLLBAR >= CHECKLIST
    # Inside the block the six columns lose twice the difference between the
    # 12px cell padding of revrook.css and the reduced one, and the narrowest
    # page of the block (768px, then 1024px beside the sidebar) holds the
    # reduced table with a classic scrollbar.
    assert "padding: 10px 12px;" in rule("main table th,\nmain table td", CSS)
    reduced = CHECKLIST - 6 * 2 * (12 - 6)
    assert reduced == 675
    for window in (768, 1024):
        assert page_width(window) - CLASSIC_SCROLLBAR >= reduced, window
    # The export history fits beside the sidebar (712px at 1024px) and is the
    # only table whose cards end at 1023px.
    narrow = media_blocks(1023)
    assert len(narrow) == 1 and "main table.rv-exports," in narrow[0]
    for other in ("rv-schedules", "rv-checklist", "rv-exceptions"):
        assert other not in narrow[0], other
    # No template changed for this: the tables keep the classes the rules address.
    system = (TEMPLATES / "system.html").read_text(encoding="utf-8")
    checklist = (TEMPLATES / "checklist.html").read_text(encoding="utf-8")
    assert '<table id="schedules" class="rv-table-cards rv-schedules">' in system
    assert '<table id="checklist" class="rv-checklist">' in checklist


# --- F2 (live retest THE-524): the border of a field against the canvas -------------


def test_the_border_of_a_field_reaches_3_to_1_on_the_canvas_and_on_white() -> None:
    light = ':root:not([data-theme="dark"]),\n[data-theme="light"]'
    assert "--pico-form-element-border-color: var(--rv-text-secondary);" in rule(light)
    border = VARIABLES["--rv-text-secondary"]
    for surface in ("--rv-canvas", "--rv-white"):
        assert contrast_ratio(border, VARIABLES[surface]) >= LARGE_MINIMUM, surface
    # The gray of revrook.css is under 3:1 on the canvas a field sits on (and
    # only just above it on white), so the rule is needed; revrook.css keeps it.
    assert contrast_ratio(VARIABLES["--rv-gray"], VARIABLES["--rv-canvas"]) < 3
    assert "--pico-form-element-border-color: var(--rv-gray);" in rule(light, CSS)
    # The active border and the focus ring are as before.
    assert "--pico-form-element-active-border-color" not in rule(light)
    assert "outline: 3px solid var(--rv-charcoal);" in rule(
        "html :is(a, button, input, select, textarea, summary, [tabindex])"
        ":focus-visible",
        CSS,
    )


# --- F3 (live retest THE-524): the result of an import at 390px ---------------------


def test_the_result_of_the_profile_editor_is_announced_after_the_swap() -> None:
    result = (TEMPLATES / "_profile_editor_result.html").read_text(encoding="utf-8")
    saved = (
        '<p id="rv-saved-profile" class="rv-status-protected" role="status" '
        'tabindex="-1" data-announce data-profile-id="{{ saved.id }}">'
    )
    imported = (
        '<p id="rv-imported" class="rv-status-protected" role="status" '
        'tabindex="-1" data-announce data-item-id="{{ imported.item_id }}">'
    )
    assert saved in result and imported in result
    # After the swap the script focuses the first marked message of the swapped
    # target and scrolls it to the top of the view, under the heading of its card.
    assert 'document.addEventListener("htmx:afterSwap", announceSwapped);' in SCRIPT
    assert 'var message = target.querySelector("[data-announce]");' in SCRIPT
    assert "message.focus({ preventScroll: true });" in SCRIPT
    assert 'message.scrollIntoView({ block: "start" });' in SCRIPT
    assert "scroll-margin-top: 72px;" in rule("[data-announce]")
    # The messages after a redirect keep their own path (they are on the page
    # when it loads, so no swap announces them).
    assert "data-announce" not in (TEMPLATES / "exceptions.html").read_text(
        encoding="utf-8"
    )
    # Without script the server draws the whole page with the result in place.
    page = (TEMPLATES / PAGE_TEMPLATE).read_text(encoding="utf-8")
    assert '<div id="rv-editor-result">' in page
    assert f'{{% include "{RESULT_TEMPLATE}" %}}' in page
    context: dict[str, object] = {
        "errors": [],
        "saved": None,
        "imported": SimpleNamespace(
            item_id=5, profile_id=4, facts=3, summary=[], controls=[], control_total=51
        ),
        "preview": None,
        "profiles": [],
        "profile_id": None,
        "name": "",
        "client_id": None,
        "csrf_token": "x" * 32,
        "brand_files": frozenset(BRAND_FILES),
    }
    html = templates.get_template(RESULT_TEMPLATE).render(context)
    assert 'id="rv-imported"' in html
    assert 'tabindex="-1" data-announce data-item-id="5"' in html


# --- The lows of the reviews of the live retest (THE-530, THE-533) ------------------


def test_the_import_area_border_reaches_3_to_1_and_stays_dashed() -> None:
    # L-A: the dashed gray boundary of the file control was 2.9:1 on the canvas.
    assert rule(".rv-dropzone").strip() == "border-color: var(--rv-text-secondary);"
    border = VARIABLES["--rv-text-secondary"]
    assert contrast_ratio(border, VARIABLES["--rv-canvas"]) >= LARGE_MINIMUM
    # The dashed 2px line of revrook.css and its accent on hover, focus and
    # drag-over are untouched (their selectors outrank the single class).
    assert "border: 2px dashed var(--rv-gray);" in rule(".rv-dropzone", CSS)
    lifted = (
        ".rv-dropzone:hover,\n.rv-dropzone:focus-within,\n"
        ".rv-dropzone.is-dragover"
    )
    assert "border-color: var(--rv-accent);" in rule(lifted, CSS)
    assert "background-color: var(--rv-canvas);" in rule(".rv-dropzone", CSS)


def test_the_exceptions_head_sticks_to_the_page_from_1280px() -> None:
    # L-B: a scroll box makes the sticky head stick to the box, not the page.
    # From the first window where the register is a table and fits its page,
    # the region stops clipping; below it the rows are cards, with no head.
    table_from = block_end("main table.rv-exceptions,") + 1
    width = WIDE_TABLES["rv-exceptions"]
    assert page_width(table_from) - CLASSIC_SCROLLBAR >= width
    visible = re.search(
        r"@media \(min-width: (\d+)px\) \{\n  \.rv-exceptions-scroll \{\n"
        r"    overflow-x: visible;\n  \}\n\}",
        FOLLOW_UP,
    )
    assert visible is not None and int(visible.group(1)) == table_from
    assert "overflow-x: auto;" in rule(".rv-table-scroll", CSS)
    assert "position: sticky;" in rule("main table thead th", CSS)


def test_a_scrolling_region_is_a_tab_stop_only_while_it_scrolls() -> None:
    # L-C: the templates keep tabindex="0" (without the script the keyboard
    # always reaches a region); the script drops it while nothing scrolls.
    exceptions = (TEMPLATES / "exceptions.html").read_text(encoding="utf-8")
    result = (TEMPLATES / "_profile_editor_result.html").read_text(encoding="utf-8")
    register = 'class="rv-table-scroll rv-exceptions-scroll" role="region"'
    assert exceptions.count(register) == 1
    assert result.count('class="rv-table-scroll" role="region"') == 2
    for template in (exceptions, result):
        assert template.count('role="region"') == template.count('tabindex="0"')
    selector = "document.querySelectorAll('.rv-table-scroll[role=\"region\"]');"
    assert selector in SCRIPT
    assert "var overflow = window.getComputedStyle(region).overflowX;" in SCRIPT
    assert 'var clips = overflow === "auto" || overflow === "scroll";' in SCRIPT
    assert "if (clips && region.scrollWidth > region.clientWidth) {" in SCRIPT
    assert 'region.setAttribute("tabindex", "0");' in SCRIPT
    # A region that holds focus keeps its tab stop until focus moves on.
    assert "} else if (region !== document.activeElement) {" in SCRIPT
    assert 'region.removeAttribute("tabindex");' in SCRIPT
    # Measured again on load (fonts), on resize and after every htmx swap (the
    # counts and the preview of an import arrive in a swapped fragment).
    for hook in (
        'document.addEventListener("htmx:afterSwap", updateRegions);',
        'window.addEventListener("resize", updateRegions);',
        'window.addEventListener("load", updateRegions);',
    ):
        assert hook in SCRIPT, hook
    assert SCRIPT.index("updateRegions();\n") > SCRIPT.index("function ready() {")
