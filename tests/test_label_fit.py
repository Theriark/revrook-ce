"""The findings of the deployed acceptance of 66448bd4 (THE-1396), fixed in THE-1401.

D1: the label at the end of a score line was cut to "Design Review Samp": it was
broken at 20 characters, and those 20 characters were 153 units wide in the bold
system face of Chrome on Linux against 140 units of room. The labels are now fitted
by their drawn width (app/ui/textfit.py) and charts.js shortens a line a browser
still draws too wide. A month at the right end of the review horizon crossed the
border of its card. D2: after a lost graphics context was restored the sky of a
scene was black. D4: the dates of the evidence freshness table of a client
overview broke. The pure functions are tested here; the pages need PostgreSQL
(DATABASE_URL) and are skipped without it; CI has no browser, so the scripts are
read as text and the live check is in the task report.
"""

import re
from datetime import date, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.ui.brand import STATIC_DIR
from app.ui.dashboard import (
    CHART_RIGHT,
    LABEL_INSET,
    LABEL_LINES,
    LABEL_ROOM,
    LABEL_SIZE,
    WIDE_CHART,
    label_lines,
    short_name,
)
from app.ui.horizon import EDGE_ROOM, HORIZON_WIDTH, review_horizon
from app.ui.textfit import ELLIPSIS, fit_lines, shorten, text_width
from helpers import NOW
from html_structure import structure_problems
from test_revamp_markup import parents
from ui_helpers import make_report, seed_client, sign_in

SAMPLE = "Design Review Sample Client"
FORTY = "Northbridge Regional Managed IT Services Cooperative Ltd"
LABEL_X = WIDE_CHART.width - WIDE_CHART.right + LABEL_INSET
SHEET = (STATIC_DIR / "css/revamp.css").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", SHEET, flags=re.DOTALL)
CHARTS_JS = (STATIC_DIR / "js/charts.js").read_text(encoding="utf-8")
SCENES_JS = (STATIC_DIR / "js/scenes.js").read_text(encoding="utf-8")
TSPAN = re.compile(r"<tspan[^>]*>([^<]*)</tspan>")
MONTH_TEXT = re.compile(
    r'<text class="rv-horizon-month" x="([0-9.]+)" y="71" text-anchor="(middle|end)">'
)


# --- D1: the labels at the ends of the score lines ---------------------------------


def test_the_room_of_a_label_is_the_gutter_of_the_drawing_less_its_air() -> None:
    assert LABEL_ROOM == CHART_RIGHT - LABEL_INSET - 4 == 136
    # The width the deployed browser measured for the line that was cut (153.3)
    assert round(text_width("Design Review Sample", LABEL_SIZE)) == 153


def test_the_founder_sample_is_whole_on_two_lines_within_the_room() -> None:
    lines = label_lines(SAMPLE)
    assert lines == ("Design Review", "Sample Client")
    assert " ".join(lines) == SAMPLE
    assert all(text_width(line, LABEL_SIZE) <= LABEL_ROOM for line in lines)


def test_a_name_of_forty_characters_or_more_fits_and_ends_in_an_ellipsis() -> None:
    assert len(FORTY) >= 40
    for name in (FORTY, "A" * 60, "Supercalifragilisticexpialidocious Holdings"):
        lines = label_lines(name)
        assert 1 <= len(lines) <= LABEL_LINES
        assert lines[-1].endswith(ELLIPSIS)
        assert all(text_width(line, LABEL_SIZE) <= LABEL_ROOM for line in lines)
        one = short_name(name)
        assert one.endswith(ELLIPSIS) and text_width(one, LABEL_SIZE) <= LABEL_ROOM


def test_fitting_keeps_whole_words_and_wide_letters_count_wide() -> None:
    # A line is broken between words; "W" is three times as wide as "i"
    assert fit_lines("Alder Ltd", 136, 12, 2) == ("Alder Ltd",)
    assert text_width("WWW", 12) > 3 * text_width("iii", 12)
    assert shorten("Alder and Finch Ltd", 60, 12) == "Alder..."
    # A character the table does not know counts wide, a full-width one an em
    assert text_width("\u0416", 12) == text_width("W", 12)
    assert text_width("\u6f22", 12) == 12
    # An accented capital is as wide as its letter
    assert text_width("\u00c9", 12) == text_width("E", 12)


async def test_home_draws_the_sample_label_whole_in_its_text(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx, SAMPLE)
    await make_report(ui_browser, csrf, client_id)
    html = (await ui_browser.get("/")).text
    assert structure_problems(html) == []
    start = html.index('<svg class="rv-chart rv-chart-wide"')
    wide = html[start : html.index("</svg>", start) + len("</svg>")]
    label = wide.split(f'<text x="{LABEL_X}"', 1)[1].split("</text>", 1)[0]
    # Both lines of the whole name are tspans of the one text of the line, and the
    # text carries no title, since nothing is cut
    assert TSPAN.findall(label) == ["Design Review", "Sample Client"]
    assert "<title>" not in label
    # The group of the line stands in the wide drawing, its text in the group and
    # both tspans in the text (the parent of each, by its x)
    assert parents(wide, "data-series", str(client_id)) == ["rv-chart rv-chart-wide"]
    assert parents(wide, "x", str(LABEL_X)) == ["rv-chart-line", "", ""]


def test_the_chart_script_measures_and_shortens_a_label_that_still_overflows() -> None:
    assert "function fitLabels(root)" in CHARTS_JS
    assert "getComputedTextLength() > room" in CHARTS_JS
    prepare = CHARTS_JS.split("function prepare(root) {", 1)[1].split("\n  }\n", 1)[0]
    assert "fitLabels(root);" in prepare


# --- the months at the ends of the review horizon ----------------------------------


def test_a_month_at_the_right_end_is_named_up_to_the_edge() -> None:
    # On January 1 the January a year ahead stands on the last day: its name ends
    # at the edge of the drawing, without its year
    last = review_horizon([], date(2027, 1, 1)).months[-1]
    assert last.label == "Jan 2028" and last.at_edge
    assert (last.text_x, last.anchor, last.name, last.year) == (
        str(HORIZON_WIDTH),
        "end",
        "Jan",
        "",
    )
    # Any month that close to the end, January or not
    october = review_horizon([], date(2026, 10, 5)).months[-1]
    assert float(october.x) > HORIZON_WIDTH - EDGE_ROOM and october.anchor == "end"
    # Elsewhere a month is centred on its tick, a January with its year
    first = review_horizon([], date(2026, 12, 30)).months[0]
    assert (first.text_x, first.anchor, first.name, first.year) == (
        first.x,
        "middle",
        "Jan",
        "2027",
    )
    assert all(
        not month.at_edge for month in review_horizon([], date(2026, 10, 26)).months
    )


def test_a_phone_names_a_january_without_its_year() -> None:
    phone = r"@media \(max-width: 599px\) \{\s*\.rv-horizon-year \{\s*display: none;"
    assert re.search(phone, CSS) is not None


async def test_the_year_of_a_january_is_a_tspan_of_its_month(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    added = await ui_browser.post(
        f"/clients/{client_id}/exceptions",
        data={
            "csrf_token": csrf,
            "control_id": load_library().controls[0].id,
            "owner": "Synthetic Owner",
            "reason": "Accepted for the test.",
            "review_date": (NOW.date() + timedelta(days=12)).isoformat(),
        },
    )
    assert added.status_code == 303, added.text
    html = (await ui_browser.get(f"/clients/{client_id}/exceptions")).text
    assert structure_problems(html) == []
    years = parents(html, "class", "rv-horizon-year")
    assert len(years) <= 1 and set(years) <= {"rv-horizon-month"}
    drawing = html.split('<section class="rv-horizon"', 1)[1].split("</svg>", 1)[0]
    anchors = MONTH_TEXT.findall(drawing)
    assert 11 <= len(anchors) <= 12
    assert all(anchor == "middle" or x == str(HORIZON_WIDTH) for x, anchor in anchors)


# --- D2: the sky after a restored graphics context ---------------------------------


def test_a_restored_context_takes_its_ground_from_the_stylesheet_again() -> None:
    after = SCENES_JS.split('"webglcontextrestored",', 1)[1]
    restored = after.split("{ signal }", 1)[0]
    assert "applyGround();" in restored
    ground = SCENES_JS.split("function applyGround() {", 1)[1].split("\n  }\n", 1)[0]
    assert "groundOf(root)" in ground and "renderer.setClearColor(next, 1);" in ground
    # The renderer is still disposed whole when the stage goes
    assert "renderer.dispose();\n    renderer.forceContextLoss();" in SCENES_JS


# --- D4: the dates of the freshness table ------------------------------------------


async def test_the_freshness_dates_of_an_overview_never_break(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await make_report(ui_browser, csrf, client_id)
    html = (await ui_browser.get(f"/clients/{client_id}")).text
    assert structure_problems(html) == []
    table = html.split('<table id="freshness">', 1)[1].split("</table>", 1)[0]
    rows = table.count('<th scope="row">')
    assert rows > 0 and table.count('<td class="rv-date">') == 2 * rows
