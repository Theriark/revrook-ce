"""The clients list and the client overview (docs/design-system.md, Clients).

The view model tests use the three worked clients of the report tests and need no
database. The page tests need PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.library import load_library
from app.evidence.service import EvidenceContext
from app.reports.view import ReportView, build_view
from app.scoring.display import format_fixed
from app.scoring.snapshot import parse_snapshot, snapshot_document
from app.ui.clientlist import (
    ALL_PROTECTED,
    PAGE_SIZE,
    ClientCard,
    LastReport,
    ListQuery,
    filter_counts,
    last_report_of,
    last_reports,
    paginate,
    read_query,
    select_rows,
)
from app.ui.common import FormError
from app.ui.overview import domain_lines
from html_structure import structure_problems
from tools import report_clients
from tools.score_inputs import AS_OF
from ui_helpers import NAME, STATUS, STATUS_SPAN, make_report, seed_client, sign_in

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
LIST = (TEMPLATES / "clients.html").read_text(encoding="utf-8")
OVERVIEW = (TEMPLATES / "client_overview.html").read_text(encoding="utf-8")
CLIENT_NAV = (TEMPLATES / "_client_nav.html").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
OVERVIEW_PARTS = (
    "period-picker",
    "posture",
    "summary",
    "status-counts",
    "needs-attention",
    "domains",
    "freshness",
    "recent-changes",
)
RING_TITLE = re.compile(r'<title id="ring-(\d+)-title">([^<]+)</title>')
ROW_HEADING = re.compile(r'<th scope="row" data-label="Client">')
PILL = re.compile(
    r'<span class="rv-status-([a-z-]+)"><span[^>]*>[^<]*</span> ([^<]+)</span>'
)
NO_REPORT = '<span class="rv-cell-note">No report yet</span>'


def view_of(name: str) -> ReportView:
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        report_clients.context_for(name),
        report_clients.previous_bytes(LIBRARY, name),
    )


def report_of(name: str) -> LastReport:
    return last_report_of(parse_snapshot(report_clients.snapshot_bytes(LIBRARY, name)))


def card(
    number: int,
    name: str,
    report: LastReport | None = None,
    days_old: int | None = None,
    exports: int = 0,
) -> ClientCard:
    newest = None if days_old is None else NOW - timedelta(days=days_old)
    return ClientCard(number, name, exports, newest, days_old, report)


def cards() -> list[ClientCard]:
    return [
        card(1, "Alder and Finch Ltd", report_of("A"), 2, 6),
        card(2, "Birch Logistics", report_of("B"), 40, 3),
        card(3, "Cedar Dental Group", report_of("C"), 0, 1),
        card(4, "Dune Marine", None, 5, 1),
        card(5, "elm and oak", None, None, 0),
    ]


# --- the last report of a client ----------------------------------------------------


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_the_last_report_is_scored_as_the_report_was(name: str) -> None:
    report = report_of(name)
    view = view_of(name)
    assert report.score == view.result.score
    assert report.score_text == format_fixed(view.result.score)
    assert report.band == view.result.band
    assert report.insufficient == view.result.insufficient
    assert report.counts == view.counts
    assert 0 <= report.score_share <= 100
    assert report.day == "2026-10-17"
    assert report.ring_dash.endswith(" 188.5")


def test_the_pills_count_what_needs_a_look_worst_first() -> None:
    a = report_of("A")
    assert [pill.text for pill in a.pills] == ["7 need attention", "1 not checked"]
    assert [pill.key for pill in a.pills] == ["needs-attention", "not-checked"]
    b = report_of("B")
    assert [pill.text for pill in b.pills] == [
        "11 not protected",
        "11 need attention",
        "12 not checked",
    ]
    assert a.needs_work == 7 and b.needs_work == 22

    def only(key: str, count: int) -> LastReport:
        counts = tuple(
            (label, count if label.key == key else 0) for label, _ in a.counts
        )
        return LastReport(NOW, Fraction(90), "90.0", 90, "Good", False, counts)

    assert only("protected", 0).pills == ()
    assert only("protected", 50).pills == (ALL_PROTECTED,)
    assert [pill.text for pill in only("needs-attention", 1).pills] == [
        "1 needs attention"
    ]


def test_last_reports_read_the_documents_and_skip_a_bad_one() -> None:
    a = snapshot_document(report_clients.inputs(LIBRARY, "A", AS_OF))
    earlier = AS_OF - timedelta(days=9)
    b = snapshot_document(report_clients.inputs(LIBRARY, "B", earlier))
    found = last_reports([(1, a), (2, b), (3, {"not": "a snapshot"})])
    assert sorted(found) == [1, 2]
    assert found[1].score_text == report_of("A").score_text
    assert found[2].day == "2026-10-08"


# --- the query, the rows and the pages ----------------------------------------------


def test_the_query_writes_only_what_differs_from_the_defaults() -> None:
    assert ListQuery().params() == ""
    assert ListQuery().params(show="needs-work") == "?show=needs-work"
    assert ListQuery(show="needs-work", page=3).params(page=1) == "?show=needs-work"
    assert ListQuery(q="Alder Finch").params() == "?q=Alder+Finch"
    assert ListQuery(q="a&b").params(show="all") == "?q=a%26b"
    assert ListQuery(sort="score", order="desc").params() == "?sort=score&order=desc"
    assert ListQuery().params(density="compact") == "?density=compact"
    assert ListQuery(density="compact").params(density="comfortable") == ""


def test_a_heading_click_sorts_a_column_in_its_first_order_then_the_other() -> None:
    query = ListQuery()
    assert query.next_order("name") == "desc"
    assert query.next_order("score") == "asc"
    assert query.next_order("evidence") == "desc"
    assert ListQuery(sort="score").next_order("score") == "desc"
    assert ListQuery(sort="score", order="desc").next_order("score") == "asc"
    assert query.aria_sort("name") == "ascending" and query.aria_sort("score") == ""
    newest = ListQuery(sort="evidence", order="desc")
    assert newest.aria_sort("evidence") == "descending"
    assert query.sort_words == "name, A to Z"
    assert ListQuery(sort="score").sort_words == "score, lowest first"
    assert newest.sort_words == "newest evidence, newest first"


def test_the_query_is_read_and_a_value_that_is_not_known_is_refused() -> None:
    query = read_query(
        "  Alder   Finch ", "needs-work", "score", "desc", "compact", " 2 "
    )
    assert query == ListQuery(
        "Alder Finch", "needs-work", "score", "desc", "compact", 2
    )
    assert read_query("", "all", "name", "asc", "comfortable", "1") == ListQuery()
    assert len(read_query("x" * 300, "all", "name", "asc", "comfortable", "1").q) == 200
    for arguments in (
        ("", "nonsense", "name", "asc", "comfortable", "1"),
        ("", "all", "colour", "asc", "comfortable", "1"),
        ("", "all", "name", "up", "comfortable", "1"),
        ("", "all", "name", "asc", "dense", "1"),
        ("", "all", "name", "asc", "comfortable", "0"),
        ("", "all", "name", "asc", "comfortable", "-1"),
        ("", "all", "name", "asc", "comfortable", "two"),
        ("", "all", "name", "asc", "comfortable", "1234567"),
    ):
        with pytest.raises(FormError) as caught:
            read_query(*arguments)
        assert caught.value.status_code == 422


def test_the_rows_are_searched_filtered_and_sorted_with_the_missing_last() -> None:
    rows = cards()

    def ids(query: ListQuery) -> list[int]:
        return [row.id for row in select_rows(rows, query)]

    assert ids(ListQuery()) == [1, 2, 3, 4, 5]
    assert ids(ListQuery(order="desc")) == [5, 4, 3, 2, 1]
    assert ids(ListQuery(q="AND")) == [1, 5]
    assert ids(ListQuery(show="needs-work")) == [1, 2, 3]
    assert ids(ListQuery(show="no-report")) == [4, 5]
    assert ids(ListQuery(show="no-evidence")) == [5]
    assert ids(ListQuery(q="zzz")) == []
    by_score = select_rows(rows, ListQuery(sort="score"))
    scores = [row.report.score for row in by_score if row.report is not None]
    assert scores == sorted(scores) and [row.id for row in by_score[3:]] == [4, 5]
    worst_last = select_rows(rows, ListQuery(sort="score", order="desc"))
    assert [row.report.score for row in worst_last[:3] if row.report] == sorted(
        scores, reverse=True
    )
    assert [row.id for row in worst_last[3:]] == [4, 5]
    newest = select_rows(rows, ListQuery(sort="evidence", order="desc"))
    assert [row.id for row in newest] == [3, 1, 4, 2, 5]
    oldest = select_rows(rows, ListQuery(sort="evidence"))
    assert [row.id for row in oldest] == [2, 4, 1, 3, 5]


def test_the_filter_counts_follow_the_search_and_not_the_filter() -> None:
    rows = cards()
    assert filter_counts(rows, ListQuery(show="no-report")) == {
        "all": 5,
        "needs-work": 3,
        "no-report": 2,
        "no-evidence": 1,
    }
    assert filter_counts(rows, ListQuery(q="and")) == {
        "all": 2,
        "needs-work": 1,
        "no-report": 1,
        "no-evidence": 1,
    }


def test_the_pages_hold_fifty_rows_and_a_number_past_the_end_is_the_last() -> None:
    rows = [card(number, f"Client {number:03d}") for number in range(1, 121)]
    first = paginate(rows, 1)
    assert (first.number, first.pages, first.total) == (1, 3, 120)
    assert (first.start, first.end, len(first.items)) == (1, PAGE_SIZE, PAGE_SIZE)
    last = paginate(rows, 99)
    assert (last.number, last.start, last.end, len(last.items)) == (3, 101, 120, 20)
    empty = paginate([], 1)
    assert (empty.pages, empty.start, empty.end, empty.items) == (1, 0, 0, [])
    assert card(1, "x", days_old=0).age_text == "today"
    assert card(1, "x", days_old=1).age_text == "yesterday"
    assert card(1, "x", days_old=12).age_text == "12 days ago"
    assert card(1, "x").age_text == ""


# --- the overview -------------------------------------------------------------------


def test_the_domain_lines_carry_the_weight_the_score_and_a_bar() -> None:
    view = view_of("A")
    lines = domain_lines(view.domains)
    assert [line.code for line in lines] == [row.code for row in view.domains]
    for line, row in zip(lines, view.domains, strict=True):
        assert (line.weight, line.score_text) == (row.weight, row.score_text)
        assert line.total == sum(count for _, count in row.counts)
        assert 0 <= line.protected <= line.total
        if line.total:
            assert line.segments and line.segments[0].x == "0.00"
            widths = sum(Fraction(seg.width) for seg in line.segments)
            assert abs(widths - 100) < Fraction(1, 10)


# --- the templates ------------------------------------------------------------------


def test_the_list_template_has_its_parts_and_names_every_column_for_a_phone() -> None:
    for part in ("client-filters", 'id="clients"', "clients-none", "clients-empty"):
        assert part in LIST, part
    assert 'id="add-client"' in LIST and 'name="csrf_token"' in LIST
    assert "<img" not in LIST and "url(" not in LIST
    assert LIST.count('data-label="') == 5
    assert 'role="img" aria-labelledby="ring-{{ row.id }}-title"' in LIST
    assert "s.status(pill)" in LIST and "s.status(no_evidence)" in LIST
    assert 'aria-sort="' in LIST and 'class="rv-sort"' in LIST
    assert "rv-table-compact" in LIST and 'class="rv-pager"' in LIST
    assert 'href="/clients{{ query.params(' in LIST


def test_the_overview_template_has_every_part_and_the_client_header() -> None:
    for part in OVERVIEW_PARTS:
        assert f'id="{part}"' in OVERVIEW, part
    assert "<img" not in OVERVIEW and "url(" not in OVERVIEW
    assert OVERVIEW.count('role="img"') == 1
    assert 'aria-labelledby="posture-ring-title"' in OVERVIEW
    assert "See which export to refresh" in OVERVIEW
    assert "Period {{ period_start }} to {{ period_end }}" in OVERVIEW
    assert "<details" in OVERVIEW and "Show the numbers" in OVERVIEW
    assert 'class="rv-page-header rv-client-header"' in CLIENT_NAV
    assert 'href="/clients">Clients</a>' in CLIENT_NAV
    assert "client_actions is defined" in CLIENT_NAV
    assert 'href="/{{ action.path }}"' in CLIENT_NAV


# --- the pages ----------------------------------------------------------------------


async def test_the_list_shows_the_last_report_and_answers_every_query(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    other_id = await seed_client(db_engine, ui_ctx, "Other Client Ltd")
    before = await ui_browser.get("/clients")
    assert before.status_code == 200
    assert structure_problems(before.text) == []
    assert len(ROW_HEADING.findall(before.text)) == 2
    assert RING_TITLE.findall(before.text) == []
    assert before.text.count(NO_REPORT) == 2
    assert 'id="clients-empty"' not in before.text

    await make_report(ui_browser, csrf, client_id)
    page = await ui_browser.get("/clients")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    rings = RING_TITLE.findall(html)
    assert [int(found) for found, _ in rings] == [client_id]
    assert "at the last report" in rings[0][1]
    pills = PILL.findall(html)
    assert pills and all(words.strip() for _, words in pills)
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
    assert any(key == "needs-attention" or key == "not-protected" for key, _ in pills)
    assert html.count(NO_REPORT) == 1
    assert f'href="/clients/{other_id}"' in html and NAME in html
    assert "2026-10-15" in html  # the newest export, two days before the test clock

    narrowed = await ui_browser.get("/clients", params={"show": "no-report"})
    assert narrowed.status_code == 200
    assert len(ROW_HEADING.findall(narrowed.text)) == 1
    assert "Other Client Ltd" in narrowed.text
    assert 'aria-current="true"' in narrowed.text
    nothing = await ui_browser.get("/clients", params={"q": "zzz"})
    assert nothing.status_code == 200 and 'id="clients-none"' in nothing.text
    assert structure_problems(nothing.text) == []
    searched = await ui_browser.get("/clients", params={"q": "other", "show": "all"})
    assert len(ROW_HEADING.findall(searched.text)) == 1
    assert 'value="other"' in searched.text
    compact = await ui_browser.get("/clients", params={"density": "compact"})
    assert 'class="rv-clients rv-table-compact"' in compact.text
    sorted_page = await ui_browser.get(
        "/clients", params={"sort": "score", "order": "desc", "page": "7"}
    )
    assert sorted_page.status_code == 200
    assert 'aria-sort="descending"' in sorted_page.text
    assert len(ROW_HEADING.findall(sorted_page.text)) == 2
    for query in (
        {"show": "nonsense"},
        {"sort": "colour"},
        {"order": "up"},
        {"density": "dense"},
        {"page": "0"},
        {"page": "two"},
    ):
        refused = await ui_browser.get("/clients", params=query)
        assert refused.status_code == 422, query
        assert "Synthetic" not in refused.text


async def test_the_overview_shows_the_posture_the_domains_and_the_changes(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await seed_client(db_engine, ui_ctx, "Other Client Ltd")
    page = await ui_browser.get(f"/clients/{client_id}")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    for part in OVERVIEW_PARTS:
        assert f'id="{part}"' in html, part
    assert html.count('aria-current="page"') == 3  # the rail, the tabs, the breadcrumb
    assert 'href="/clients">Clients</a>' in html
    assert "Review flagged controls" in html and "Prepare a report" in html
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
    assert 'id="posture-ring-title"' in html and "No earlier report" in html
    assert "Evidence coverage" in html and "Controls that need work" in html
    assert html.count('class="rv-domain"') == len(LIBRARY.domains)
    assert "Weight " in html and "See which export to refresh" in html
    assert ('id="attention-empty"' in html) != ('<ol class="rv-attention">' in html)
    assert "Client added" in html and "Evidence imported" in html
    assert "Other Client Ltd" not in html

    await make_report(ui_browser, csrf, client_id)
    after = await ui_browser.get(f"/clients/{client_id}")
    assert after.status_code == 200 and structure_problems(after.text) == []
    assert "Report snapshot made" in after.text
    assert "Unchanged since 2026-10-17" in after.text


async def test_the_checklist_has_the_filter_chips_and_the_control_its_verdict(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get(f"/clients/{client_id}/checklist")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert html.count('aria-current="page"') == 3  # the rail, the tabs, the breadcrumb
    assert 'id="show-all" class="rv-chip" href' in html
    assert 'aria-current="true">All controls <span class="rv-chip-count">' in html
    assert 'id="show-flagged" class="rv-chip"' in html
    assert 'id="checklist-count">' in html and "controls shown." in html
    assert "No report has been made for this client yet" in html
    assert '<table id="checklist" class="rv-checklist">' in html
    headings = html.count('<th scope="row"><a class="rv-control-link"')
    assert headings == len(LIBRARY.controls)
    assert html.count('<td data-label="Why it needs a look"></td>') > 0
    assert '<ul class="rv-flags">' in html and ", gate control</span>" in html
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))

    narrowed = await ui_browser.get(
        f"/clients/{client_id}/checklist", params={"show": "flagged"}
    )
    assert narrowed.status_code == 200 and structure_problems(narrowed.text) == []
    assert 'id="show-flagged" class="rv-chip" href="/clients/' in narrowed.text
    assert 'aria-current="true">Changed or needs a look' in narrowed.text
    assert '<td data-label="Why it needs a look"></td>' not in narrowed.text

    control_id = LIBRARY.controls[0].id
    control = await ui_browser.get(f"/clients/{client_id}/controls/{control_id}")
    html = control.text
    assert control.status_code == 200 and structure_problems(html) == []
    assert ">Back to the checklist</a>" in html
    assert '<h2 class="rv-control-title">' in html
    assert f"<li>{control_id}</li>" in html and "<li>Weight " in html
    assert '<section class="rv-verdict" id="control-status"' in html
    for fact in ("Evidence dated", "State of the evidence", "Evidence type"):
        assert f"<dt>{fact}</dt>" in html, fact
    assert '<p class="rv-rule">' in html and 'id="exceptions-empty"' in html
    assert '<p id="suggestion" class="rv-suggestion-text">' in html
    assert 'aria-describedby="by_when-help"' in html
    assert '<span class="rv-notes-saving" aria-hidden="true">' in html
    assert 'id="note-status" class="rv-notes-status" aria-live="polite"' in html
    assert len(STATUS_SPAN.findall(html)) == len(STATUS.findall(html))
