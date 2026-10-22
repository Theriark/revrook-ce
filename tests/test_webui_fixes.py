"""The corrective fixes of the web UI retest (THE-505, REV-131).

Seen on Development at 1440, 768 and 390px: the clients list broke its last report
one letter a line at 768px and pushed the page sideways; an address no page answers
was raw JSON; the result of an import did not say why most of the checklist stayed
unchecked; the summary of a details element had no visible focus ring; the
navigation and the client tabs scrolled sideways with nothing to show it; and the
trend chart was an unreadable thumbnail on a phone, its labels on the dates of the
axis when several clients scored 0. Also the profile editor skipped step 3 when the
file was refused, and opened on the first client instead of the one it was called
for.

The page tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from datetime import timedelta
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.ui.auth import templates
from app.ui.brand import BRAND_FILES
from app.ui.dashboard import (
    LABEL_GAP,
    NARROW_CHART,
    WIDE_CHART,
    ReportPoint,
    trend_chart,
)
from app.ui.profiles import RESULT_TEMPLATE, controls_reading
from helpers import create_test_client
from html_structure import structure_problems
from tools.score_inputs import AS_OF
from ui_helpers import sign_in

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "app/static/css/revrook.css").read_text(encoding="utf-8")
TEMPLATES = ROOT / "app/ui/templates"
NAV = (TEMPLATES / "_nav.html").read_text(encoding="utf-8")
CLIENT_NAV = (TEMPLATES / "_client_nav.html").read_text(encoding="utf-8")
HOME = (TEMPLATES / "home.html").read_text(encoding="utf-8")
# The body of the trend card of Home and the chart macros it draws with (THE-850).
TREND = (TEMPLATES / "_trend_chart.html").read_text(encoding="utf-8")
CHART = (TEMPLATES / "_chart.html").read_text(encoding="utf-8")
LIBRARY = load_library()
# A placeholder for the CSRF field of a rendered template; not a real token.
PLACEHOLDER_TOKEN = "x" * 32
EDITOR = "/imports/profile-editor"


def rule(selector: str) -> str:
    """The declarations of the (last) rule with exactly this selector."""
    found = re.findall(rf"\n{re.escape(selector)} \{{([^}}]*)\}}", CSS)
    assert found, selector
    return found[-1]


def media(query: str) -> str:
    """The first media block with this query."""
    found = re.search(rf"@media {re.escape(query)} \{{(.*?)\n\}}\n", CSS, re.DOTALL)
    assert found is not None, query
    return found.group(1)


def point(client_id: int, score: int, days_ago: int = 0) -> ReportPoint:
    moment = AS_OF - timedelta(days=days_ago)
    return ReportPoint(client_id, moment, Fraction(score), "Good", False, 1, 1)


def render_result(**context: object) -> str:
    base: dict[str, object] = {
        "errors": [],
        "saved": None,
        "imported": None,
        "preview": None,
        "profiles": [],
        "profile_id": None,
        "name": "",
        "client_id": None,
        "csrf_token": PLACEHOLDER_TOKEN,
        "brand_files": frozenset(BRAND_FILES),
    }
    return templates.get_template(RESULT_TEMPLATE).render({**base, **context})


# --- 1: the clients list between 768 and 1023px ---------------------------------------


def test_the_clients_list_is_cards_below_the_sidebar_two_a_row_at_768() -> None:
    # The five columns had 704px at 768px: the band of the last report broke one
    # letter a line and the page overflowed. The cards now start where the
    # sidebar ends, two to a row from 768px, one on a phone; the band and the
    # date never break; beside the sidebar the row actions wrap until 1280px.
    cards = media("(max-width: 1023px)")
    assert "main table.rv-clients" in cards and "display: block;" in cards
    assert re.search(r"\.rv-clients thead \{[^}]*clip: rect\(0 0 0 0\);", cards)
    assert "content: attr(data-label);" in cards
    tablet = media("(min-width: 768px) and (max-width: 1023px)")
    assert re.search(r"\.rv-clients tbody \{[^}]*display: grid;", tablet)
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in tablet
    phone = media("(max-width: 767px)")
    assert ".rv-density" in phone and "main table.rv-clients" not in phone
    assert re.search(r'button\[type="submit"\] \{[^}]*width: 100%;', phone)
    assert "white-space: nowrap;" in rule(".rv-posture-score")
    assert "white-space: nowrap;" in rule(".rv-posture-note")
    beside = media("(max-width: 1279px)")
    assert re.search(r"\.rv-row-actions \{[^}]*white-space: normal;", beside)


# --- 2: an address no page answers --------------------------------------------------


async def test_an_unknown_address_is_the_problem_page_signed_out_and_in(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    missing = await ui_browser.get("/no-such-page")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("text/html")
    assert structure_problems(missing.text) == []
    assert 'class="rv-problem"' in missing.text
    assert "There is no page at this address." in missing.text
    # Signed out, the page is the signed-out shell: no navigation, no user.
    assert 'class="rv-nav"' not in missing.text
    await sign_in(ui_browser, db_engine)
    signed = await ui_browser.get("/no-such-page")
    assert signed.status_code == 404 and 'class="rv-nav"' in signed.text
    assert structure_problems(signed.text) == []
    assert signed.headers["cache-control"] == "no-store"
    # A method a page does not take is the same page, with the Allow header kept.
    wrong = await ui_browser.post("/glossary", data={"csrf_token": "x"})
    assert wrong.status_code == 405
    assert wrong.headers["content-type"].startswith("text/html")
    assert "GET" in wrong.headers["allow"]
    assert "does not accept" in wrong.text
    # The API, the probes and the static files are not pages: JSON as before.
    for path in ("/api/v1/no-such", "/static/css/no-such.css"):
        answer = await ui_browser.get(path)
        assert answer.status_code == 404, path
        assert answer.headers["content-type"].startswith("application/json"), path


# --- 3: what an import changes --------------------------------------------------------


def test_the_controls_that_read_a_source_are_listed() -> None:
    # A control names its sources by the letters of the report (H is the leavers
    # file) and its fields by those letters; the field map says which importer
    # carries each field, so the importer code of an import is matched through it.
    leavers = controls_reading(LIBRARY, "leavers-csv")
    assert [item.id for item in leavers] == ["PC-GOV-04"]
    devices = controls_reading(LIBRARY, "device-inventory")
    assert 1 < len(devices) < len(LIBRARY.controls)
    assert "PC-DEV-02" in {item.id for item in devices}
    assert controls_reading(LIBRARY, "H") == ()
    assert controls_reading(LIBRARY, "no-such-source") == ()


def test_the_import_result_says_which_controls_the_export_reaches() -> None:
    html = render_result(
        client_id=7,
        imported={
            "item_id": 3,
            "profile_id": 2,
            "facts": 5,
            "summary": [("leavers.rows", "2")],
            "controls": [("PC-GOV-04", "Leavers lose their access")],
            "control_total": 51,
        },
    )
    assert 'id="rv-import-reach"' in html
    assert "read by 1 of the 51 controls" in html
    assert "The other controls keep the status they had" in html
    link = 'href="/clients/7/controls/PC-GOV-04">Leavers lose their access</a>'
    assert link in html and 'href="/clients/7/checklist"' in html
    assert "make a report to carry the change there" in html
    none = render_result(
        imported={
            "item_id": 3,
            "profile_id": 2,
            "facts": 0,
            "summary": [],
            "controls": [],
            "control_total": 51,
        }
    )
    assert "No control of the library reads this export" in none
    assert "rv-import-controls" not in none


# --- 4: the focus ring of a details summary -------------------------------------------


def test_a_details_summary_keeps_the_focus_ring() -> None:
    # Pico's details summary:focus-visible:not([role]) outranked the shared ring
    # and drew a hairline in the (transparent) focus colour instead.
    ring = rule("html details summary:focus-visible:not([role])")
    assert "outline: 3px solid var(--rv-focus);" in ring
    assert "outline-offset: 2px;" in ring


# --- 5: the strips that scroll sideways ---------------------------------------------


def test_the_scrolling_strips_fade_their_last_link_as_the_cue() -> None:
    nav_fade = rule(".rv-nav-strip::after")
    fade = "linear-gradient(to right, transparent, var(--rv-{}) 70%)"
    assert fade.format("rail") in nav_fade
    assert "pointer-events: none;" in nav_fade
    tabs_fade = rule(".rv-tabs-strip::after")
    assert fade.format("surface") in tabs_fade
    # Space after the last link, so with it in view nothing sits under the fade.
    assert "width: 32px;" in rule(".rv-nav::after")
    assert "width: 32px;" in rule(".rv-tabs-strip > nav > ul::after")
    # In the sidebar the navigation does not scroll, so the fade goes.
    assert re.search(
        r"\n  \.rv-nav-strip::after,\n  \.rv-nav::after \{\n    display: none;", CSS
    )
    assert "grid-area: nav;" in rule(".rv-nav-strip")
    assert "grid-area" not in rule(".rv-nav")
    wrapped = '<div class="rv-nav-strip">\n<nav class="rv-nav" aria-label="Main">'
    assert wrapped in NAV and NAV.count("</nav>\n</div>") == 1
    assert '<div class="rv-tabs-strip">\n<nav class="rv-client-nav"' in CLIENT_NAV
    assert "scrollbar-width: thin;" in rule("main nav")


# --- 7: the trend chart on a phone ----------------------------------------------------


def test_the_trend_chart_has_a_narrow_drawing_for_a_phone() -> None:
    names = {1: "Alder and Finch Ltd", 2: "Birch Logistics"}
    points = [point(1, 40, 30), point(1, 70), point(2, 55)]
    now = AS_OF + timedelta(days=1)
    wide = trend_chart(points, names, now)
    narrow = trend_chart(points, names, now, size=NARROW_CHART)
    assert (wide.kind, wide.labelled, wide.width) == ("wide", True, 640)
    assert (wide.height, wide.left, wide.right) == (220, 36, 490)
    assert (narrow.kind, narrow.labelled, narrow.width) == ("narrow", False, 320)
    assert (narrow.height, narrow.left, narrow.right) == (200, 36, 304)
    assert WIDE_CHART.dates == 4 and NARROW_CHART.dates == 3
    # The first date is written from its tick and the last up to it, so neither
    # is cut at an edge; the narrow drawing names three dates, not four.
    anchors = [anchor for _, _, anchor in wide.x_ticks]
    assert anchors == ["start", "middle", "middle", "end"]
    assert [label for _, label, _ in wide.x_ticks] == [
        "2026-07-20",
        "2026-08-19",
        "2026-09-18",
        "2026-10-18",
    ]
    assert [anchor for _, _, anchor in narrow.x_ticks] == ["start", "middle", "end"]
    assert [label for _, label, _ in narrow.x_ticks] == [
        "2026-07-20",
        "2026-09-03",
        "2026-10-18",
    ]
    for line in narrow.lines:
        assert narrow.left <= float(line.last_x) <= narrow.right
        assert narrow.top <= float(line.last_y) <= narrow.bottom
    # The same lines, numbers and dashes in both drawings.
    assert [line.rows for line in narrow.lines] == [line.rows for line in wide.lines]
    assert [line.dash for line in narrow.lines] == [line.dash for line in wide.lines]
    assert narrow.reports == wide.reports == 3


def test_a_stack_of_labels_never_sits_on_the_dates_of_the_axis() -> None:
    # Six clients at a score of 0 end their lines at the floor of the plot; their
    # labels, pushed apart by 14 units, reached the dates under the chart.
    names = {number: f"Client {number}" for number in range(1, 7)}
    chart = trend_chart([point(number, 0) for number in names], names, AS_OF)
    labels = sorted(float(line.label_y) for line in chart.lines)
    assert max(labels) <= chart.bottom - LABEL_GAP / 2
    assert min(labels) >= chart.top + LABEL_GAP / 2
    assert [round(b - a, 1) for a, b in pairwise(labels)] == [LABEL_GAP] * 5
    # One client at 0 keeps its label beside the end of its line, lifted by half
    # a gap so that the lower half of the text stays inside the plot.
    alone = trend_chart([point(1, 0)], names, AS_OF)
    assert float(alone.lines[0].label_y) == alone.bottom - LABEL_GAP / 2
    assert float(alone.lines[0].last_y) == alone.bottom


def test_the_home_template_draws_both_charts_and_a_legend() -> None:
    trend = HOME.split('id="trend"', 1)[1].split("</section>", 1)[0]
    assert '{% include "_trend_chart.html" %}' in trend
    assert "{% for chart in (trend, trend_narrow) %}" in TREND
    assert 'class="rv-chart rv-chart-{{ chart.kind }}"' in CHART
    assert "{% if chart.labelled %}" in CHART
    assert 'text-anchor="{{ anchor }}"' in CHART
    assert '<ul class="rv-chart-legend" aria-label="The clients drawn">' in TREND
    assert 'class="rv-chart-key"' in TREND and "{{ line.name }}" in TREND
    assert "display: none;" in rule(".rv-chart-narrow,\n.rv-chart-legend")
    phone = re.search(
        r"@media \(max-width: 599px\) \{\n  \.rv-chart-wide \{([^}]*)\}", CSS
    )
    assert phone is not None and "display: none;" in phone.group(1)


# --- 8 and 9: the profile editor ----------------------------------------------------


def test_step_three_is_always_there_so_the_numbers_never_skip() -> None:
    refused = SimpleNamespace(
        hidden_headers=0,
        choices=[],
        offered=[],
        missing=[],
        problem="The file is missing the column user_id.",
        shown=[],
        rows=[],
        rejected=0,
        more_rows=False,
        assumed_utc=False,
    )
    html = render_result(preview=refused)
    assert '<h2 id="step-3-title" class="rv-step-title">' in html
    assert 'id="rv-preview-waiting"' in html and 'id="rv-preview"' not in html
    assert "Choose a file column for the columns of the source" in html
    for step in ("2", "4", "5"):
        assert f'<legend><span class="rv-step-number">{step}</span>' in html, step


async def test_the_profile_editor_opens_on_the_client_it_was_called_for(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    first = await create_test_client(db_engine, ui_ctx, "Alder Ltd")
    second = await create_test_client(db_engine, ui_ctx, "Birch Ltd")
    page = await ui_browser.get(f"{EDITOR}?client_id={second}")
    assert page.status_code == 200
    assert f'<option value="{second}" selected>' in page.text
    assert f'<option value="{first}" selected>' not in page.text
    for query in ("", "?client_id=abc", f"?client_id={second + 1000}"):
        plain = await ui_browser.get(f"{EDITOR}{query}")
        assert plain.status_code == 200, query
        clients = plain.text.split('id="client_id"', 1)[1].split("</select>", 1)[0]
        assert " selected>" not in clients, query
    evidence = await ui_browser.get(f"/clients/{second}/evidence")
    assert f'href="{EDITOR}?client_id={second}"' in evidence.text
