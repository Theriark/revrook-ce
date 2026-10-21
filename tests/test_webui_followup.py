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
from pathlib import Path

from app.ui.brand import ASSET_FILES

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app/static"
TEMPLATES = ROOT / "app/ui/templates"
CSS = (STATIC / "css/revrook.css").read_text(encoding="utf-8")
FOLLOW_UP = (STATIC / "css/revrook-retest.css").read_text(encoding="utf-8")
SCRIPT = (STATIC / "js/revrook.js").read_text(encoding="utf-8")
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
STYLESHEET = 'href="/static/css/revrook.css?v={{ asset_version }}"'
FOLLOW_UP_LINK = 'href="/static/css/revrook-retest.css?v={{ asset_version }}"'


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
