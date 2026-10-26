"""The Home dashboard (docs/design-system.md, Dashboard): the view model and the page.

The view model tests use the three worked clients of the report tests and need no
database. The page tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from datetime import timedelta
from fractions import Fraction
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.models import AuditEvent
from app.reports.status import NEEDS_ATTENTION, NOT_PROTECTED
from app.reports.view import ReportView, build_view
from app.scoring.display import format_fixed
from app.scoring.snapshot import snapshot_document
from app.ui.dashboard import (
    CHART_LEFT,
    CHART_RIGHT,
    CHART_WIDTH,
    DELETED_CLIENT,
    LABEL_GAP,
    SYSTEM_ACTOR,
    AttentionItem,
    ClientPosture,
    ReportPoint,
    ago,
    attention_items,
    change_lines,
    change_since_reports,
    deleted_client_name,
    domain_bars,
    posture_of,
    prioritised,
    report_points,
    ring_dash,
    sparkline,
    trend_chart,
    weekly_series,
)
from app.ui.viewmodels import read_earlier
from helpers import NOW, create_admin, login
from html_structure import structure_problems
from tools import report_clients
from tools.score_inputs import AS_OF
from ui_helpers import STATUS, STATUS_SPAN, make_report, seed_client, sign_in

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "app/ui/templates/home.html").read_text(encoding="utf-8")
# The body of the trend card and the chart macros it draws with (THE-850).
TREND = (ROOT / "app/ui/templates/_trend_chart.html").read_text(encoding="utf-8")
CHART = (ROOT / "app/ui/templates/_chart.html").read_text(encoding="utf-8")
SECTIONS = ("stats", "rookery", "needs-attention", "trend", "domains", "recent-changes")
DRIVER = re.compile(
    r'<li class="rv-driver[^"]*" data-client="(\d+)" data-name="([^"]*)"'
)
POLYLINE = re.compile(r'<polyline points="([^"]+)"')
STAT_VALUE = re.compile(r'id="stat-evidence">\s*<a class="rv-stat-value"[^>]*>(\d+)<')
DOMAIN_SUM = re.compile(r'<span class="rv-domain-sum">(\d+) of (\d+) protected</span>')
SCROLLED_TABLE = '<div class="rv-table-scroll">\n<table>'
TREND_TABLE = (
    '<div class="rv-table-scroll">\n<table class="rv-table-cards rv-trend-table">'
)


def view_of(name: str) -> ReportView:
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        report_clients.context_for(name),
        report_clients.previous_bytes(LIBRARY, name),
    )


def posture(name: str, client_id: int = 1, evidence: int = 3) -> ClientPosture:
    earlier = read_earlier(report_clients.previous_bytes(LIBRARY, name))
    return posture_of(
        client_id, report_clients.NAMES[name], view_of(name), earlier, evidence
    )


def event(
    action: str,
    *,
    detail: dict[str, object] | None = None,
    actor: int | None = 1,
    target_type: str | None = None,
    target_id: str | None = None,
    minutes_ago: int = 5,
) -> AuditEvent:
    return AuditEvent(
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        actor_user_id=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
    )


# --- the ring, the sparkline and the words ------------------------------------------


def test_the_ring_fills_the_share_of_the_score() -> None:
    assert ring_dash(0) == "0.0 188.5"
    assert ring_dash(50) == "94.2 188.5"
    assert ring_dash(100) == "188.5 188.5"
    assert ring_dash(150) == ring_dash(100)
    assert ring_dash(-5) == ring_dash(0)


def test_a_sparkline_needs_two_known_values_and_spans_its_box() -> None:
    assert sparkline([7]) == ""
    assert sparkline([None, 3, None]) == ""
    assert sparkline([]) == ""
    points = sparkline([0, 10, 5]).split()
    assert len(points) == 3
    assert points[0] == "2.0,26.0"
    assert points[1] == "48.0,2.0"
    assert points[2] == "94.0,14.0"
    # A flat line sits on the floor of the box and a gap is skipped, not drawn.
    assert sparkline([4, 4]) == "2.0,26.0 94.0,26.0"
    assert sparkline([1, None, 3]).split() == ["2.0,26.0", "94.0,2.0"]


def test_how_long_ago_is_told_in_words() -> None:
    assert ago(NOW, NOW) == "just now"
    assert ago(NOW - timedelta(seconds=59), NOW) == "just now"
    assert ago(NOW - timedelta(minutes=1), NOW) == "1 minute ago"
    assert ago(NOW - timedelta(minutes=45), NOW) == "45 minutes ago"
    assert ago(NOW - timedelta(hours=3), NOW) == "3 hours ago"
    assert ago(NOW - timedelta(days=1), NOW) == "yesterday"
    assert ago(NOW - timedelta(days=12), NOW) == "12 days ago"
    assert ago(NOW - timedelta(days=40), NOW) == "2026-09-07"
    assert ago(NOW + timedelta(hours=1), NOW) == "just now"


# --- the posture of a client --------------------------------------------------------


def test_a_posture_carries_the_score_the_band_and_the_change() -> None:
    a = posture("A")
    view = view_of("A")
    assert a.score_text == format_fixed(view.result.score)
    assert a.band == view.result.band and not a.insufficient
    assert 0 <= a.score_share <= 100 and a.score_share == int(view.result.score)
    assert a.counts == view.counts
    assert (a.protected, a.needs_work, a.counted) == (42, 7, 50)
    assert a.change_text == "Up 40.5 since 2026-07-17"
    assert a.protected_before is not None and a.needs_work_before is not None
    assert a.ring_dash == ring_dash(a.score_share)
    b = posture("B")
    assert b.change_text == "No earlier report"
    assert b.protected_before is None and b.needs_work_before is None
    c = posture("C")
    assert c.change_text == "Down 40.5 since 2026-07-17"


def test_the_change_across_clients_compares_only_those_with_a_report() -> None:
    a, b, c = posture("A", 1), posture("B", 2), posture("C", 3)
    assert change_since_reports([b], "protected") == "No earlier report to compare with"
    # A was C last quarter and C was A: the two changes cancel out exactly.
    assert change_since_reports([a, b, c], "protected").startswith("Unchanged since")
    delta = a.protected - (a.protected_before or 0)
    assert delta != 0
    expected = f"{delta:+d} since the last reports of 1 client"
    assert change_since_reports([a, b], "protected") == expected
    assert change_since_reports([a, c], "needs_work").endswith("of 2 clients")


# --- what needs attention -----------------------------------------------------------


def test_attention_is_ranked_gates_first_then_not_protected_by_weight() -> None:
    items: list[AttentionItem] = []
    for number, name in enumerate(("A", "B", "C"), start=1):
        client_name = report_clients.NAMES[name]
        items += attention_items(number, client_name, view_of(name), set())
    assert items and all(
        item.label in (NOT_PROTECTED, NEEDS_ATTENTION) for item in items
    )
    ordered = prioritised(items)
    keys = [
        (0 if item.gate else 1, 0 if item.label == NOT_PROTECTED else 1, -item.weight)
        for item in ordered
    ]
    assert keys == sorted(keys)
    assert ordered[0].href.startswith(f"/clients/{ordered[0].client_id}/controls/PC-")
    # The reasons beyond the status itself, in lower case: old evidence, an exception.
    first = items[0].control_id
    excepted = attention_items(1, "A", view_of("A"), {first})
    by_id = {item.control_id: item for item in excepted}
    assert by_id[first].why.endswith("open exception")
    for item in items:
        assert item.why == item.why.lower()
        assert item.label.text.lower() not in item.why


# --- the breakdown by domain --------------------------------------------------------


def test_domain_bars_add_the_clients_up_in_the_order_of_the_library() -> None:
    bars = domain_bars([*view_of("A").domains, *view_of("B").domains])
    assert [bar.code for bar in bars] == [domain.code for domain in LIBRARY.domains]
    a = {row.code: dict(row.counts) for row in view_of("A").domains}
    b = {row.code: dict(row.counts) for row in view_of("B").domains}
    for bar in bars:
        for label, count in bar.counts:
            assert count == a[bar.code][label] + b[bar.code][label]
        assert bar.total == sum(count for _, count in bar.counts)
        widths = sum(Fraction(seg.width) for seg in bar.segments)
        assert bar.segments[0].x == "0.00"
        assert abs(widths - 100) < Fraction(1, 10)
        assert all(seg.count > 0 for seg in bar.segments)


# --- the stored reports: points, weeks and the chart --------------------------------


def documents() -> list[tuple[int, dict[str, object]]]:
    a = snapshot_document(report_clients.inputs(LIBRARY, "A", AS_OF))
    older = snapshot_document(
        report_clients.inputs(LIBRARY, "C", AS_OF - timedelta(days=40))
    )
    b = snapshot_document(
        report_clients.inputs(LIBRARY, "B", AS_OF - timedelta(days=10))
    )
    return [(1, a), (2, b), (1, older), (3, {"not": "a snapshot"})]


def test_report_points_read_the_snapshots_and_skip_a_bad_one() -> None:
    points = report_points(documents())
    assert [(point.client_id, point.as_of) for point in points] == [
        (1, AS_OF - timedelta(days=40)),
        (2, AS_OF - timedelta(days=10)),
        (1, AS_OF),
    ]
    newest = points[-1]
    assert newest.score == view_of("A").result.score
    assert (newest.protected, newest.needs_work) == (42, 7)
    assert newest.band == view_of("A").result.band


def test_the_weekly_series_sums_the_newest_report_of_each_client() -> None:
    points = report_points(documents())
    created = [AS_OF - timedelta(days=100), AS_OF - timedelta(days=3)]
    weeks = weekly_series(points, created, AS_OF + timedelta(days=1))
    assert len(weeks) == 12
    assert weeks[0].clients == 1 and weeks[-1].clients == 2
    # Before the first report there is nothing to sum; after it, the sums grow.
    assert weeks[0].protected is None and weeks[0].needs_work is None
    last = weeks[-1]
    assert last.protected == points[-1].protected + points[1].protected
    assert last.needs_work == points[-1].needs_work + points[1].needs_work
    middle = next(week for week in weeks if week.end >= AS_OF - timedelta(days=20))
    assert middle.protected == points[0].protected


def test_the_trend_chart_draws_a_line_per_client_and_keeps_the_labels_apart() -> None:
    names = {1: "Alder and Finch Ltd", 2: "Birch Logistics"}
    chart = trend_chart(report_points(documents()), names, AS_OF + timedelta(days=1))
    assert [line.name for line in chart.lines] == list(names.values())
    alder, birch = chart.lines
    assert len(alder.points.split()) == 2 and birch.points == ""
    assert len(alder.rows) == 2 and len(birch.rows) == 1
    assert alder.dash == "" and birch.dash == "6 3"
    for line in chart.lines:
        assert CHART_LEFT <= float(line.last_x) <= CHART_WIDTH - CHART_RIGHT
    assert chart.reports == 3
    assert len(chart.x_ticks) == 4 and chart.x_ticks[-1][1] == "2026-10-18"
    assert [label for _, label in chart.y_ticks] == ["0", "50", "100"]
    # Two clients with the same score at the same moment get labels 14px apart.
    same = [
        ReportPoint(1, AS_OF, Fraction(70), "Good", False, 40, 5),
        ReportPoint(2, AS_OF, Fraction(70), "Good", False, 40, 5),
    ]
    paired = trend_chart(same, names, AS_OF + timedelta(hours=1))
    first, second = (float(line.label_y) for line in paired.lines)
    assert abs(first - second) == pytest.approx(LABEL_GAP)
    assert paired.lines[0].last_y == paired.lines[1].last_y
    # A client that is gone keeps its line under a neutral name; names are shortened.
    gone = trend_chart(same, {1: "A" * 40}, AS_OF + timedelta(hours=1))
    assert gone.lines[0].name == DELETED_CLIENT
    assert gone.lines[1].short_name == "A" * 17 + "..."
    assert trend_chart([], names, AS_OF).lines == ()


# --- the recent changes -------------------------------------------------------------


def test_the_audit_trail_is_put_into_words_with_the_client_and_the_person() -> None:
    names = {7: "Alder and Finch Ltd"}
    users = {1: "admin"}
    lines = change_lines(
        [
            event("evidence.added", detail={"client_id": 7, "source_code": "x"}),
            event("snapshot.created", detail={"client_id": 7}, target_id="3"),
            event("client.created", target_type="client", target_id="7"),
            event("client.deleted", target_type="client", target_id="8", actor=None),
            event("report.export", detail={"kind": "qbr"}, actor=9),
            event("exception.closed", detail={"client_id": 8}, minutes_ago=90),
            event("something.new", minutes_ago=3000),
        ],
        names,
        users,
        NOW,
    )
    assert [line.words for line in lines] == [
        "Evidence imported",
        "Report snapshot made",
        "Client added",
        "Client deleted",
        "Quarterly security review exported",
        "Exception closed",
        "Something new",
    ]
    assert lines[0].client_name == "Alder and Finch Ltd"
    assert lines[0].href == "/clients/7/evidence"
    assert lines[1].href == "/clients/7/reports"
    assert lines[2].href == "/clients/7"
    assert lines[3].client_name == deleted_client_name(8) and lines[3].href == ""
    assert lines[3].actor == SYSTEM_ACTOR
    assert lines[4].client_name == "" and lines[4].actor == "A removed user"
    assert lines[5].client_name == deleted_client_name(8) and lines[5].href == ""
    assert lines[0].actor == "admin" and lines[0].ago == "5 minutes ago"
    assert lines[5].ago == "1 hour ago" and lines[6].ago == "2 days ago"
    assert lines[0].when_iso.endswith("+00:00")
    assert lines[0].when_text == "2026-10-17 11:55:00"


# --- the template -------------------------------------------------------------------


def test_the_template_draws_every_part_without_an_image_or_a_colour_alone() -> None:
    for part in SECTIONS:
        assert f'id="{part}"' in TEMPLATE, part
    assert 'id="home-empty"' in TEMPLATE
    assert "<img" not in TEMPLATE and "url(" not in TEMPLATE
    # The sparkline (the score bars are the _drivers.html macro, THE-1189); the
    # trend chart holds links, so it is a group (the _chart.html macro), drawn once
    # for every width it has (_trend_chart.html)
    assert TEMPLATE.count('role="img"') == 1
    assert '<div id="trend-body">\n{% include "_trend_chart.html" %}' in TEMPLATE
    assert 'c.score_chart(chart, "trend-title", "trend"' in TREND
    assert 'role="group" aria-labelledby="{{ title_id }} {{ prefix }}-desc' in CHART
    assert "s.status(" in TEMPLATE and "Signed in as {{ user.username }}" in TEMPLATE
    assert "<details" in TEMPLATE and "<caption>" in TEMPLATE


def test_the_breakdown_by_domain_is_a_bar_per_domain_with_the_counts_folded() -> None:
    # Seen on Development at 1440 and 390px: a table of six columns beside the bars
    # was wider than its card and pushed the page sideways. The bars stand alone,
    # one per domain across the card, and the counts sit in a table under "Show the
    # numbers" that scrolls inside the card on a narrow phone.
    domains = TEMPLATE.split('id="domains"', 1)[1].split("</section>", 1)[0]
    assert '<ul class="rv-domains">' in domains
    assert 'class="rv-domain-sum"' in domains
    assert "of {{ bar.total }} protected" in domains
    assert domains.count('class="rv-bar"') == 1
    assert '<details class="rv-chart-data">' in domains
    assert SCROLLED_TABLE in domains
    assert domains.index('class="rv-bar"') < domains.index("<table>")


def test_the_numbers_behind_the_trend_scroll_inside_their_card() -> None:
    # A long client name in the first column must not widen the card on a phone:
    # the table scrolls inside the card, like the table of the breakdown. The
    # table is the score_table macro of _chart.html, which the trend card draws.
    # Below 768px each of its reports is a card (THE-1313).
    assert "c.score_table(trend," in TREND
    assert TREND_TABLE in CHART
    assert CHART.count("<table") == 1


# --- the page -----------------------------------------------------------------------


async def test_a_fresh_install_shows_what_to_do_first(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    assert (await login(client)).status_code == 303
    page = await client.get("/")
    assert page.status_code == 200
    html = page.text
    assert structure_problems(html) == []
    assert "Signed in as admin" in html
    assert 'id="home-empty"' in html and "Add the first client" in html
    for part in SECTIONS:
        assert f'id="{part}"' not in html, part
    assert 'aria-current="page"' in html


async def test_the_dashboard_shows_every_part_for_a_client_with_evidence(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get("/")
    assert page.status_code == 200
    html = page.text
    assert structure_problems(html) == []
    assert 'id="home-empty"' not in html
    for part in SECTIONS:
        assert f'id="{part}"' in html, part
    shown = STATUS_SPAN.findall(html)
    found = STATUS.findall(html)
    assert shown and len(shown) == len(found)
    cards = DRIVER.findall(html)
    assert [int(found_id) for found_id, _ in cards] == [client_id]
    assert cards[0][1] == "Synthetic Client Ltd"
    assert 'id="drivers-summary"' in html and 'id="drivers-data"' in html
    assert f'href="/clients/{client_id}"' in html
    assert "No earlier report" in html
    assert 'id="trend-empty"' in html
    assert ('id="attention-empty"' in html) != ('<ol class="rv-attention">' in html)
    assert "Evidence imported" in html and "Client added" in html
    assert 'id="stat-clients"' in html and 'id="stat-evidence"' in html
    # The backup export of the seeded client is 100 days old: a refresh is due.
    refresh = STAT_VALUE.search(html)
    assert refresh is not None and int(refresh.group(1)) >= 1
    # One bar and one protected share per domain, each share within its total.
    sums = DOMAIN_SUM.findall(html)
    assert len(sums) == len(LIBRARY.domains)
    assert all(int(protected) <= int(total) for protected, total in sums)
    assert sum(int(total) for _, total in sums) == len(LIBRARY.controls)

    report = await make_report(ui_browser, csrf, client_id)
    assert report.startswith(f"/clients/{client_id}/reports/")
    after = await ui_browser.get("/")
    assert after.status_code == 200
    html = after.text
    assert structure_problems(html) == []
    assert 'id="trend-empty"' not in html
    assert "<circle" in html and "Show the numbers" in html
    assert "Report snapshot made" in html
    assert "Unchanged since 2026-10-17" in html
    assert "since the last reports of 1 client" in html
    assert POLYLINE.search(html) is not None  # the sparklines of the stat cards


async def test_the_home_page_lists_a_client_whose_evidence_cannot_be_read(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    # Two clients, one of them with hostile text in its name: the page escapes it.
    await sign_in(ui_browser, db_engine)
    await seed_client(db_engine, ui_ctx)
    hostile = '<b id="main">Finch</b>'
    await seed_client(db_engine, ui_ctx, hostile)
    page = await ui_browser.get("/")
    assert page.status_code == 200
    assert structure_problems(page.text) == []
    assert '<b id="main">' not in page.text and "&lt;b id=" in page.text
    assert len(DRIVER.findall(page.text)) == 2
    assert 'id="unread"' not in page.text
