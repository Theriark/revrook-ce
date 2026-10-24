"""The range of the Home "Score over time" chart (THE-1134, REV-281).

A range of `days` keeps the stored reports whose instant is `now - days <= as_of <=
now`: one point per stored report, not per day, compared as instants, so a time
zone cannot move a report across the edge. A client with no report in the range has
no line. A client with one in the range and an earlier one enters the plot from the
earlier one: the segment between the two is cut at the left edge, `continues_from`
names the earlier report, and its marks, rows and count stay those of the range.
The pure functions are tested without a database; the page and the fragment need
PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from datetime import UTC, date, datetime, timedelta, timezone
from fractions import Fraction

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.snapshots import store_snapshot
from app.ui.dashboard import (
    NARROW_CHART,
    WIDE_CHART,
    ReportPoint,
    TrendLine,
    _chart_y,
    trend_chart,
)
from helpers import FakeClock
from tools import report_clients
from ui_helpers import seed_client, sign_in

LIBRARY = load_library()
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
NAMES = {1: "Alder", 2: "Birch"}
LEFT = f"{WIDE_CHART.left:.1f}"
MARK = re.compile(r'<a class="rv-mark" href="(/clients/\d+/reports/\d+)" data-tip="')
LINE = re.compile(r'<polyline points="([^"]+)"')


def at(
    instant: datetime, score: int, snapshot_id: int, client_id: int = 1
) -> ReportPoint:
    return ReportPoint(
        client_id, instant, Fraction(score), "Good", False, 1, 1, snapshot_id
    )


def ago(count: int, score: int, snapshot_id: int, client_id: int = 1) -> ReportPoint:
    return at(NOW - timedelta(days=count), score, snapshot_id, client_id)


def one_line(points: list[ReportPoint], window: int) -> TrendLine:
    chart = trend_chart(points, NAMES, NOW, days=window)
    assert len(chart.lines) == 1
    return chart.lines[0]


def coordinates(line: TrendLine) -> list[tuple[str, str]]:
    found = []
    for pair in line.points.split():
        x, y = pair.split(",")
        found.append((x, y))
    return found


def paths(line: TrendLine) -> list[str]:
    return [mark.path for mark in line.marks]


# The evidence: "now" is the 24th of October; the stored reports are the 24th of
# August (61 days before), the 23rd of September (31 days) and the 23rd of
# October (1 day).
THREE = [ago(61, 40, 1), ago(31, 55, 2), ago(1, 70, 3)]


def test_90_days_holds_every_stored_report_and_a_line_through_them() -> None:
    line = one_line(THREE, 90)
    days = [day for day, _, _ in line.rows]
    assert days == ["2026-08-24", "2026-09-23", "2026-10-23"]
    assert len(line.marks) == 3 and len(coordinates(line)) == 3
    assert line.continues_from == ""


def test_30_and_7_days_hold_one_report_and_the_line_enters_from_before() -> None:
    for window in (30, 7):
        line = one_line(THREE, window)
        # Only the report of the 23rd of October is in the range: one mark, one row.
        assert [day for day, _, _ in line.rows] == ["2026-10-23"]
        assert paths(line) == ["clients/1/reports/3"]
        # The line is the segment from the 23rd of September, cut at the left edge,
        # to that report; the report of the 24th of August is not involved.
        assert line.continues_from == "2026-09-23"
        entering, last = coordinates(line)
        assert entering[0] == LEFT
        assert last == (line.last_x, line.last_y)
        assert trend_chart(THREE, NAMES, NOW, days=window).reports == 1


def test_the_line_enters_at_the_height_the_line_between_the_reports_has() -> None:
    # 0 at 31 days, 60 at 1 day: on the edge of 30 days, a thirtieth of the way, it
    # is at 2.
    points = [ago(31, 0, 1), ago(1, 60, 2)]
    entering, _ = coordinates(one_line(points, 30))
    assert entering == (LEFT, f"{_chart_y(Fraction(2)):.1f}")
    narrow = trend_chart(points, NAMES, NOW, days=30, size=NARROW_CHART).lines[0]
    assert coordinates(narrow)[0][0] == f"{NARROW_CHART.left:.1f}"


def test_the_edges_of_the_range_are_inclusive_and_exact() -> None:
    start = NOW - timedelta(days=30)
    second = timedelta(seconds=1)
    just_before = at(start - second, 10, 2)
    on_edge = at(start, 50, 1)
    just_after = at(start + second, 20, 3)
    at_now = at(NOW, 60, 4)
    after_now = at(NOW + second, 90, 5)
    # On the edge the report is in the range, and nothing is cut for it.
    line = one_line([just_before, on_edge, at_now, after_now], 30)
    assert paths(line) == ["clients/1/reports/1", "clients/1/reports/4"]
    assert line.continues_from == ""
    assert coordinates(line)[0][0] == LEFT
    # A second after the edge it is in too; the second before it is what the line
    # enters from, never a mark. A report after now is never drawn.
    line = one_line([just_before, just_after, after_now], 30)
    assert paths(line) == ["clients/1/reports/3"]
    assert line.continues_from == "2026-09-24"
    assert len(coordinates(line)) == 2


def test_the_range_compares_instants_not_the_zone_they_are_written_in() -> None:
    start = NOW - timedelta(days=30)
    local = timezone(timedelta(hours=5))
    same = at(start.astimezone(local), 30, 1)
    earlier = at((start - timedelta(minutes=1)).astimezone(local), 10, 2)
    line = one_line([earlier, same], 30)
    assert paths(line) == ["clients/1/reports/1"]
    assert line.continues_from == "2026-09-24"


def test_no_report_in_the_range_is_no_line_even_with_an_earlier_one() -> None:
    assert trend_chart([], NAMES, NOW, days=30).lines == ()
    only_earlier = [ago(31, 50, 1), ago(45, 60, 2)]
    chart = trend_chart(only_earlier, NAMES, NOW, days=30)
    assert chart.lines == () and chart.reports == 0
    # Nothing is made up: the earlier report is not repeated as a flat line. It is
    # drawn where its own range holds it.
    assert trend_chart(only_earlier, NAMES, NOW, days=90).reports == 2


def test_one_report_alone_is_one_mark_and_no_line() -> None:
    line = one_line([ago(1, 50, 1)], 30)
    assert len(line.marks) == 1 and line.points == "" and line.continues_from == ""


def test_the_line_enters_from_the_newest_report_before_the_range() -> None:
    points = [ago(80, 10, 1), ago(40, 30, 2), ago(1, 70, 3)]
    line = one_line(points, 30)
    assert line.continues_from == "2026-09-14"
    assert [day for day, _, _ in line.rows] == ["2026-10-23"]


def test_each_client_has_its_own_line_and_its_own_entry() -> None:
    points = [
        ago(31, 40, 1),
        ago(2, 60, 2),
        ago(3, 50, 3, client_id=2),  # no report before the range: a lone mark
    ]
    chart = trend_chart(points, NAMES, NOW, days=30)
    alder, birch = chart.lines
    assert alder.continues_from == "2026-09-23" and len(coordinates(alder)) == 2
    assert birch.continues_from == "" and birch.points == ""
    assert chart.reports == 2


# --- the page and the fragment ---------------------------------------------


async def store_reports(
    engine: AsyncEngine, client_id: int, clock: FakeClock, plan: list[tuple[str, int]]
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        for name, back in plan:
            snapshot = report_clients.inputs(
                LIBRARY, name, clock() - timedelta(days=back)
            )
            await store_snapshot(
                session, client_id, snapshot, date(2026, 7, 1), date(2026, 9, 30)
            )


async def test_home_ranges_over_the_stored_reports_of_a_client(
    ui_browser: httpx.AsyncClient,
    db_engine: AsyncEngine,
    ui_ctx: EvidenceContext,
    clock: FakeClock,
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await store_reports(db_engine, client_id, clock, [("A", 61), ("B", 31), ("A", 1)])

    ninety = await ui_browser.get("/", params={"days": "90"})
    assert ninety.status_code == 200
    assert len(MARK.findall(ninety.text)) == 6  # three reports, drawn wide and narrow
    assert [len(points.split()) for points in LINE.findall(ninety.text)] == [3, 3]

    for window in ("30", "7"):
        page = await ui_browser.get("/", params={"days": window})
        fragment = await ui_browser.get(
            "/charts/trend", params={"days": window}, headers={"HX-Request": "true"}
        )
        for text in (page.text, fragment.text):
            assert len(MARK.findall(text)) == 2  # the one report of the range
            lines = LINE.findall(text)
            assert [len(points.split()) for points in lines] == [2, 2]
            assert all(points.startswith("36.0,") for points in lines)
            assert 'id="trend-empty"' not in text
