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

import re
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evidence.service import EvidenceContext
from app.ui.brand import ASSET_FILES
from app.ui.clients import EXCEPTION_DONE
from app.ui.reports import DETAILS_SAVED
from helpers import NOW
from html_structure import structure_problems
from test_brand_contrast import BODY_MINIMUM, VARIABLES, contrast_ratio
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


def rule(selector: str, css: str = FOLLOW_UP) -> str:
    """The declarations of the (last) rule with exactly this selector."""
    found = re.findall(rf"\n{re.escape(selector)} \{{([^}}]*)\}}", css)
    assert found, selector
    return found[-1]


def without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


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
    assert "var STRIP_TAIL = 48;" in SCRIPT
    remaining = "scroller.scrollWidth - scroller.clientWidth - scroller.scrollLeft"
    assert remaining in SCRIPT
    assert 'strip.setAttribute(\n        "data-scroll-end",' in SCRIPT
    assert 'remaining <= STRIP_TAIL + 1 ? "true" : "false"' in SCRIPT
    for event in ('"scroll", update', '"resize", update', '"load", update'):
        assert event in SCRIPT, event
    unwanted = ("eval(", "fetch(", "XMLHttpRequest", "innerHTML", "document.write")
    for forbidden in unwanted:
        assert forbidden not in SCRIPT, forbidden


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
    found = re.search(
        r"@media \(min-width: 768px\) and \(max-width: 1023px\) \{(.*?)\n\}\n",
        FOLLOW_UP,
        re.DOTALL,
    )
    assert found is not None
    cards = found.group(1)
    assert re.search(r"main table\.rv-exports,\n(.*\n)*?    display: block;", cards)
    assert re.search(r"main table\.rv-schedules,\n(.*\n)*?    display: block;", cards)
    assert "content: attr(data-label);" in cards
    assert "main .rv-exports td[data-label]::before," in cards
    # An export is one card a row (a digest keeps one line); schedules two a row.
    assert re.search(
        r"\.rv-schedules tbody \{\n    display: grid;\n"
        r"    grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);",
        cards,
    )
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" not in cards.split(
        ".rv-schedules tbody {"
    )[0]
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
