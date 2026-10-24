"""The score chart when the range holds few reports, and the long labels of the
clients list and the rookery (THE-1133, REV-280).

Ruben's live evidence of 24 October: at 90 days the seeded clients had three
reports each (24 August, 23 September, 23 October) and a line each; at 30 and 7
days each had only its report of 23 October, one small dot and no line, and the
card did not say why. A line needs two reports of the same client: the card now
says when a client has one report in the range, rings that mark, keys it alone in
the legend and counts the reports of every client. Since THE-1134 the line of a
client with a report before the range enters the plot from it; that line is drawn,
its mark is not ringed, and the note names the report it comes from and its date.
Nothing is invented: the marks are the stored reports of the range and nothing
else. The renders of the templates need no database; the ranges of the seeded
Development data need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from datetime import timedelta
from fractions import Fraction
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import devseed
from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.reports.view import iso_date
from app.ui.auth import templates
from app.ui.charts import HISTORY_RANGES, RANGE_DAYS, RANGE_WORDS
from app.ui.dashboard import NARROW_CHART, ReportPoint, trend_chart
from helpers import NOW
from html_structure import structure_problems
from tools.score_inputs import AS_OF
from ui_helpers import sign_in

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app/static"
SCRIPT = (STATIC / "js/charts.js").read_text(encoding="utf-8")
CHARTS_CSS = (STATIC / "css/charts.css").read_text(encoding="utf-8")
FOLLOW_UP = (STATIC / "css/revrook-retest.css").read_text(encoding="utf-8")
TREND = (ROOT / "app/ui/templates/_trend_chart.html").read_text(encoding="utf-8")
MARK = re.compile(r'<a class="rv-mark" href="(/clients/\d+/reports/\d+)" data-tip="')
HALO = 'class="rv-mark-halo"'
SHAPE = re.compile(r'<(circle|polygon) class="rv-mark-shape"')
NAMES = {1: "Alder Ltd", 2: "Birch Ltd", 3: "Cedar Ltd", 4: "Dogwood Ltd"}
NAMES |= {5: "Elm Ltd", 6: "Fir Ltd"}
RANGES = [(value, RANGE_WORDS[value]) for value in RANGE_DAYS]


def point(client_id: int, days_ago: int, score: int = 50) -> ReportPoint:
    moment = AS_OF - timedelta(days=days_ago)
    snapshot_id = client_id * 100 + days_ago
    return ReportPoint(
        client_id, moment, Fraction(score), "Weak", False, 1, 1, snapshot_id
    )


def render_trend(points: list[ReportPoint], days: int) -> str:
    context = {
        "trend": trend_chart(points, NAMES, AS_OF, days=days),
        "trend_narrow": trend_chart(points, NAMES, AS_OF, days=days, size=NARROW_CHART),
        "days": days,
        "ranges": RANGES,
    }
    return templates.env.get_template("_trend_chart.html").render(context)


def render_history(points: list[ReportPoint], span: str, days: int) -> str:
    names = {1: NAMES[1]}
    context = {
        "history": trend_chart(points, names, AS_OF, days=days, max_lines=1),
        "history_narrow": trend_chart(
            points, names, AS_OF, days=days, max_lines=1, size=NARROW_CHART
        ),
        "client_id": 1,
        "span": span,
        "spans": HISTORY_RANGES,
        "reports_total": len(points),
        "reports_capped": False,
        "reports_cap": 500,
    }
    return templates.env.get_template("_history_chart.html").render(context)


def trend_part(html: str) -> str:
    """The body of the score card of Home, without the sparklines around it."""
    return html.split('id="trend-body"', 1)[1].split('id="domains"', 1)[0]


def keys(html: str) -> list[str]:
    return re.findall(r'<svg class="rv-chart-key".*?</svg>', html, flags=re.DOTALL)


# --- empty, one point, several points -------------------------------------------


def test_no_report_in_the_range_is_the_empty_state_and_no_note() -> None:
    html = render_trend([point(1, 40)], 30)
    assert 'id="trend-empty"' in html and "No reports in the last 30 days" in html
    assert "data-sparse" not in html and MARK.findall(html) == []
    assert "Score over time, last 30 days: no reports." in html


def test_one_report_per_client_is_ringed_marks_without_a_line_and_says_so() -> None:
    html = render_trend([point(1, 1, 40), point(2, 1, 60)], 30)
    assert "<polyline" not in html
    assert len(MARK.findall(html)) == 4  # two clients, wide and narrow
    assert html.count(HALO) == 4
    assert 'data-sparse="all"' in html
    note = "One report per client in the last 30 days, so there is no line yet"
    assert note in html
    assert "Choose 90 days to include older reports." in html
    assert html.count('<span class="rv-chart-count">1 report</span>') == 2
    # The legend keys a single report by its mark alone: no line is drawn for it.
    assert all("<line" not in key for key in keys(html)) and len(keys(html)) == 2
    assert "Score over time, last 30 days: 2 reports of 2 clients drawn." in html


def test_one_client_with_one_report_is_named_as_that_report() -> None:
    html = render_trend([point(1, 2)], 7)
    assert "One report in the last 7 days, so there is no line yet" in html
    assert "The ringed mark is that report." in html
    assert "Score over time, last 7 days: 1 report of 1 client drawn." in html


def test_several_reports_draw_lines_without_a_note_or_a_ring() -> None:
    points = [point(n, days) for n in (1, 2) for days in (61, 31, 1)]
    html = render_trend(points, 90)
    assert html.count("<polyline") == 4  # two lines, wide and narrow
    assert len(MARK.findall(html)) == 12
    assert "data-sparse" not in html and HALO not in html
    assert html.count('<span class="rv-chart-count">3 reports</span>') == 2
    assert all("<line" in key for key in keys(html))
    # At 90 days there is no longer range to invite.
    assert "Choose 90 days" not in html


def test_a_client_with_one_report_beside_lines_is_named() -> None:
    points = [point(1, 61), point(1, 31), point(1, 1), point(2, 1)]
    html = render_trend(points, 90)
    assert 'data-sparse="some"' in html
    note = "Birch Ltd has one report in the last 90 days, so it is drawn as a ringed"
    assert note in html
    assert html.count("<polyline") == 2 and html.count(HALO) == 2
    two = render_trend([*points, point(3, 2)], 90)
    assert "Birch Ltd, Cedar Ltd have one report in the last 90 days" in two
    assert "so they are drawn" in two


def test_the_ranges_of_the_founder_evidence_draw_what_is_stored() -> None:
    # Reports 61, 31 and 1 days old, as the seed of 23 October seen on the 24th:
    # 90 days hold all three and a line; 30 and 7 days hold the newest only, and
    # the line of each client enters from its report 31 days old (THE-1134).
    points = [point(n, days, 30 + n) for n in (1, 2) for days in (61, 31, 1)]
    quarter = render_trend(points, 90)
    assert len(MARK.findall(quarter)) == 12 and "data-sparse" not in quarter
    assert "data-enters" not in quarter
    entered = iso_date(AS_OF - timedelta(days=31))
    for days in (30, 7):
        html = render_trend(points, days)
        assert len(MARK.findall(html)) == 4, days
        assert html.count("<polyline") == 4 and HALO not in html
        assert "data-sparse" not in html and 'data-enters="2"' in html
        note = f"come from each client's report before the last {days} days"
        assert note in html and "which has no mark here" in html
        assert f"Alder Ltd {entered}, Birch Ltd {entered}." in html
        assert "Choose 90 days to include older reports." in html
        assert all("<line" in key for key in keys(html))
        assert ">2026-10-16<" in html  # the newest report, in the table


def test_a_line_entering_from_the_report_before_the_range_is_named() -> None:
    # One report in the range and one before it: a drawn line, not a ringed mark.
    html = render_trend([point(1, 45), point(1, 2)], 30)
    assert html.count("<polyline") == 2 and HALO not in html
    assert len(MARK.findall(html)) == 2  # the report of the range, wide and narrow
    assert "data-sparse" not in html and 'data-enters="1"' in html
    entered = iso_date(AS_OF - timedelta(days=45))
    note = "The line of Alder Ltd starts at the left edge: it comes from the report"
    assert f"{note} of {entered}, before the last 30 days, which has no mark" in html
    assert '<span class="rv-chart-count">1 report</span>' in html
    assert all("<line" in key for key in keys(html))
    # Beside a client with one report and none before it, which stays ringed.
    mixed = render_trend([point(1, 45), point(1, 2), point(2, 3)], 30)
    assert 'data-sparse="some" data-enters="1"' in mixed
    assert mixed.count(HALO) == 2 and mixed.count("<polyline") == 2
    assert "Birch Ltd has one report in the last 30 days, so it is drawn" in mixed
    assert ["<line" in key for key in keys(mixed)] == [True, False]


def test_every_line_has_its_own_mark_shape() -> None:
    html = render_trend([point(n, 1 + n) for n in range(1, 7)], 30)
    wide = html.split('class="rv-chart rv-chart-wide"', 1)[1].split("</svg>", 1)[0]
    shapes = re.findall(r'<(?:circle|polygon) class="rv-mark-shape"[^>]*>', wide)
    assert len(shapes) == 6
    assert SHAPE.findall(wide) == ["circle", *["polygon"] * 5]
    corners = [shape.count(",") for shape in shapes[1:]]
    assert corners == [4, 4, 3, 3, 12]  # square, diamond, two triangles, cross
    assert len(set(shapes[1:3])) == 2  # the square and the diamond differ


def test_the_history_of_one_client_says_when_older_reports_are_outside() -> None:
    points = [point(1, 200), point(1, 120), point(1, 1)]
    quarter = render_history(points, "90", 90)
    # The line enters from the report 120 days old (THE-1134): drawn, not ringed.
    assert quarter.count("<polyline") == 2 and HALO not in quarter
    entered = iso_date(AS_OF - timedelta(days=120))
    note = "The line of Alder Ltd starts at the left edge: it comes from the report"
    assert f"{note} of {entered}, before this span, which has no mark" in quarter
    assert "2 older reports are outside this span: choose All reports" in quarter
    every = render_history(points, "all", 365)
    assert "data-sparse" not in every and every.count("<polyline") == 2
    alone = render_history([point(1, 1)], "all", 90)
    assert "One report in this span" in alone and "older report" not in alone


# --- the script, the template and the stylesheet --------------------------------


def test_all_clients_switched_off_is_said_and_a_new_range_is_read_out() -> None:
    assert '<p class="rv-chart-note" data-all-off hidden>' in TREND
    assert "Every client is switched off. Press a name above" in TREND
    assert "data-chart-summary" in TREND
    assert "showAllOff(card);" in SCRIPT
    assert 'card.querySelector("[data-all-off]")' in SCRIPT
    assert 'live.setAttribute("aria-live", "polite");' in SCRIPT
    assert SCRIPT.index("announce(target);") > SCRIPT.index("animate(target);")


def test_the_marks_grow_by_scale_and_the_single_report_is_ringed() -> None:
    assert ".rv-chart a.rv-mark:focus-visible .rv-mark-shape {" in CHARTS_CSS
    assert "transform-box: fill-box;" in CHARTS_CSS
    assert ".rv-chart a.rv-mark .rv-mark-halo {" in CHARTS_CSS
    assert ".rv-chart-note {" in CHARTS_CSS and ".rv-chart-count {" in CHARTS_CSS


def rule(selector: str) -> str:
    """The declarations of a rule of the follow-up stylesheet, which revrook.css
    yields to (it is loaded after it)."""
    found = re.search(r"\n" + re.escape(selector) + r" \{([^}]*)\}", FOLLOW_UP)
    assert found is not None, selector
    return found.group(1)


def test_a_long_band_in_the_clients_list_keeps_its_own_width() -> None:
    # "Insufficient evidence" ran under the pills of the next column at 1440px:
    # the words beside the ring had a track that could shrink to nothing.
    assert "grid-template-columns: 40px auto;" in rule(".rv-posture")
    compact = rule(".rv-table-compact .rv-posture")
    assert "grid-template-columns: 28px auto;" in compact
    # revrook.css gives the words min-width 0, which let the auto track shrink
    # under the longest word anyway; the words keep their min-content width.
    assert "min-width: min-content;" in rule(".rv-posture-text")
    band = rule(".rv-posture-score")
    assert "white-space: normal;" in band and "word-break: keep-all;" in band
    assert "font-size: 20px;" in rule(".rv-posture-ring .rv-ring-value")


def test_a_client_name_in_the_rookery_is_read_whole() -> None:
    name = rule(".rv-rook-name")
    assert "text-overflow: clip;" in name and "white-space: normal;" in name
    assert "overflow-wrap: anywhere;" in name and "-webkit-line-clamp: 3;" in name
    assert "align-items: start;" in rule(".rv-two")


# --- the seeded Development data, a day after the seed ----------------------------


async def test_the_seeded_reports_a_day_later_are_drawn_as_stored(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    await devseed.seed_demo_data(factory, ui_ctx, LIBRARY, NOW - timedelta(days=1))
    stale = "Seed Stale Ltd (synthetic)"

    quarter = await ui_browser.get("/", params={"days": "90"})
    assert quarter.status_code == 200 and structure_problems(quarter.text) == []
    card = trend_part(quarter.text)
    # Tidy and Gaps: three reports and a line each; Stale: its one report.
    assert len(MARK.findall(card)) == 14 and card.count("<polyline") == 4
    assert 'data-sparse="some"' in card
    assert f"{stale} has one report in the last 90 days" in card
    assert card.count('<span class="rv-chart-count">3 reports</span>') == 2

    for days in ("30", "7"):
        page = await ui_browser.get("/", params={"days": days})
        assert page.status_code == 200 and structure_problems(page.text) == []
        card = trend_part(page.text)
        assert 'value="' + days + '" aria-pressed="true"' in card
        # Tidy and Gaps enter from their reports 31 days old (THE-1134), drawn and
        # named; Stale has its one report and nothing before it, ringed.
        assert len(MARK.findall(card)) == 6 and card.count("<polyline") == 4
        assert card.count(HALO) == 2
        assert 'data-sparse="some" data-enters="2"' in card
        assert f"{stale} has one report in the last {days} days" in card
        assert f"come from each client's report before the last {days} days" in card
        summary = f"Score over time, last {days} days: 3 reports of 3 clients drawn."
        assert summary in card
        # The range button of the card asks for the same body in place.
        fragment = await ui_browser.get(
            "/charts/trend", params={"days": days}, headers={"HX-Request": "true"}
        )
        assert fragment.status_code == 200 and "<html" not in fragment.text
        assert len(MARK.findall(fragment.text)) == 6
        assert 'data-sparse="some" data-enters="2"' in fragment.text
        assert summary in fragment.text
