"""The revamp as the application renders it (THE-1313, REV-316; review THE-1347).

tests/test_revamp.py reads the stylesheet and the templates as files; these tests
draw the pages through the application: Home with a report of a client whose name
is longer than one label line, the checklist and a control of that client under
the band and its tabs, and a missing client's problem page. The labels at the ends
of the score lines are tested as pure functions too. The pages need PostgreSQL
(DATABASE_URL) and are skipped without it.
"""

import re
from fractions import Fraction

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.ui.dashboard import (
    LABEL_GAP,
    LABEL_ROOM,
    LABEL_SIZE,
    LINE_STEP,
    WIDE_CHART,
    ReportPoint,
    label_lines,
    trend_chart,
)
from app.ui.textfit import text_width
from html_structure import structure_problems
from tools.score_inputs import AS_OF
from ui_helpers import make_report, seed_client, sign_in

LIBRARY = load_library()
LONG_NAME = "Northwind Harbour Logistics Ltd"
LABEL_X = WIDE_CHART.width - WIDE_CHART.right + 10
SHEET = '<link rel="stylesheet" href="/static/css/revamp.css?v='
GROUP_ROW = re.compile(r'<tr class="rv-group-row"><th scope="rowgroup" colspan="6">')


def report(client_id: int, score: int) -> ReportPoint:
    return ReportPoint(client_id, AS_OF, Fraction(score), "Good", False, 40, 5)


# --- the labels at the ends of the score lines --------------------------------------


def test_a_long_name_is_broken_between_its_words_not_cut() -> None:
    # Seen on Development: "Seed Gaps Ltd (synthetic)" ended "Seed Gaps Ltd (sy...".
    assert label_lines("Seed Gaps Ltd (synthetic)") == ("Seed Gaps Ltd", "(synthetic)")
    assert label_lines("Alder Ltd") == ("Alder Ltd",)
    assert label_lines(LONG_NAME) == ("Northwind Harbour", "Logistics Ltd")
    # Longer than two lines: the second ends in "...", every line within the room
    # it is drawn in (THE-1401: fitted by its width, not its number of characters)
    longest = label_lines("Very Long Client Name Holdings and Partners International")
    assert len(longest) == 2 and longest[-1].endswith("...")
    assert all(text_width(line, LABEL_SIZE) <= LABEL_ROOM for line in longest)


def test_two_line_labels_keep_their_air_and_stay_in_the_plot() -> None:
    names = {1: "Seed Gaps Ltd (synthetic)", 2: "Seed Tidy Ltd (synthetic)"}
    chart = trend_chart([report(1, 50), report(2, 50)], names, AS_OF)
    first, second = sorted(chart.lines, key=lambda line: float(line.label_y))
    assert len(first.label) == len(second.label) == 2
    gap = float(second.label_y) - float(first.label_y)
    assert gap >= LINE_STEP + LABEL_GAP
    # At a score of 0 the second line of the lowest label stays above the dates
    low = trend_chart([report(1, 0)], names, AS_OF).lines[0]
    assert float(low.label_y) + LINE_STEP <= chart.bottom - LABEL_GAP / 2


def test_too_many_long_names_fall_back_to_one_line_each() -> None:
    names = {k: f"Seed Client Number {k} (synthetic)" for k in range(1, 7)}
    chart = trend_chart([report(k, 0) for k in names], names, AS_OF)
    assert all(len(line.label) == 1 for line in chart.lines)
    assert all(line.label[0] == line.short_name for line in chart.lines)
    assert max(float(line.label_y) for line in chart.lines) <= chart.bottom


# --- the pages ----------------------------------------------------------------------


async def test_home_renders_the_band_the_keep_and_the_whole_label(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx, LONG_NAME)
    await make_report(ui_browser, csrf, client_id)
    page = await ui_browser.get("/")
    assert page.status_code == 200
    html = page.text
    assert structure_problems(html) == []
    assert SHEET in html
    # The band opens the page and the ledger stands on its foot
    assert html.index('<div class="rv-page-header">') < html.index('id="stats"')
    assert '<div class="rv-keep rv-keep-panel" id="keep-panel">' in html
    assert 'id="portfolio-gauge"' in html
    assert '<div class="rv-dash-row rv-dash-row-trend">' in html
    # The label of the line carries the whole name, on two lines
    label = f'>Northwind Harbour</tspan><tspan x="{LABEL_X}" dy="14">Logistics Ltd<'
    assert label in html
    # The numbers under the chart are cards on a phone, each cell named
    assert '<table class="rv-table-cards rv-trend-table">' in html
    for name in ("Report date", "Score", "Band"):
        assert f'<td data-label="{name}"' in html


async def test_a_client_route_renders_under_the_band_and_its_tabs(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    checklist = await ui_browser.get(f"/clients/{client_id}/checklist")
    assert checklist.status_code == 200
    html = checklist.text
    assert structure_problems(html) == []
    assert SHEET in html
    header = html.index('<div class="rv-page-header rv-client-header">')
    table = html.index('<table id="checklist"')
    assert header < html.index('<div class="rv-tabs-strip">') < table
    # The checklist in library order is grouped by domain, a heading row first
    assert len(GROUP_ROW.findall(html)) >= 2
    assert html.index('class="rv-group-row"') < html.index("<tr data-control=")
    control = LIBRARY.controls[0].id
    page = await ui_browser.get(f"/clients/{client_id}/controls/{control}")
    assert page.status_code == 200 and structure_problems(page.text) == []
    assert '<div class="rv-page-header rv-client-header">' in page.text
    assert '<details class="rv-rule-more">' in page.text
    missing = await ui_browser.get(f"/clients/{client_id + 1000}")
    assert missing.status_code == 404
    assert SHEET in missing.text and '<section class="rv-problem"' in missing.text
