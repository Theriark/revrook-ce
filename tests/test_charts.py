"""The interactive charts (docs/design-system.md, Charts; THE-850).

Every chart is the server's SVG with a table of its numbers, fed by data the
application stores anyway; `app/static/js/charts.js` adds the tooltip, the roving
keyboard, the series toggles and the in-place range swap. The pure functions are
tested without a database; the fragment routes, the ranges and the drill-downs
need PostgreSQL (DATABASE_URL) and are skipped without it.
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
from app.scoring.snapshot import snapshot_document
from app.ui.brand import ASSET_FILES
from app.ui.charts import (
    DEFAULT_HISTORY,
    HISTORY_KEYS,
    NEVER_IMPORTED,
    AgeBar,
    age_bars,
    band_counts,
    history_days,
    read_days,
    read_range,
)
from app.ui.clientlist import (
    BAND_KEYS,
    NO_REPORT_KEY,
    ClientCard,
    ListQuery,
    band_key,
    last_report_of,
    matches,
    read_band,
)
from app.ui.common import FormError
from app.ui.dashboard import (
    HISTORY_DAYS,
    NARROW_CHART,
    ReportPoint,
    WeekPoint,
    report_points,
    spark_marks,
    trend_chart,
)
from app.ui.viewmodels import CURRENT, EXPIRED, MISSING, STALE, SourceRow
from helpers import NOW, create_admin, login
from html_structure import structure_problems
from tools import report_clients
from tools.score_inputs import AS_OF
from ui_helpers import make_report, seed_client, sign_in

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
STATIC = ROOT / "app/static"
SCRIPT = (STATIC / "js/charts.js").read_text(encoding="utf-8")
CSS = (STATIC / "css/charts.css").read_text(encoding="utf-8")
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
CHART = (TEMPLATES / "_chart.html").read_text(encoding="utf-8")
TREND = (TEMPLATES / "_trend_chart.html").read_text(encoding="utf-8")
HISTORY = (TEMPLATES / "_history_chart.html").read_text(encoding="utf-8")
HOME = (TEMPLATES / "home.html").read_text(encoding="utf-8")
OVERVIEW = (TEMPLATES / "client_overview.html").read_text(encoding="utf-8")
EVIDENCE = (TEMPLATES / "evidence_imports.html").read_text(encoding="utf-8")
REPORTS = (TEMPLATES / "reports.html").read_text(encoding="utf-8")
LIST = (TEMPLATES / "clients.html").read_text(encoding="utf-8")
CHECKLIST = (TEMPLATES / "checklist.html").read_text(encoding="utf-8")
MARK = re.compile(r'<a class="rv-mark" href="(/clients/\d+/reports/\d+)" data-tip="')
PRESSED = re.compile(r'name="(days|span)" value="([^"]+)" aria-pressed="true"')
DOMAIN = LIBRARY.domains[0]


def point(
    client_id: int, score: int, days_ago: int = 0, snapshot_id: int = 0
) -> ReportPoint:
    moment = AS_OF - timedelta(days=days_ago)
    return ReportPoint(
        client_id, moment, Fraction(score), "Good", False, 1, 1, snapshot_id
    )


def source(
    code: str,
    state: object,
    days_old: int | None,
    window: int | None = 90,
) -> SourceRow:
    captured = None if days_old is None else NOW - timedelta(days=days_old)
    expires = None
    if captured is not None and window is not None:
        expires = captured + timedelta(days=window)
    return SourceRow(
        code=code,
        name=code.replace("-", " ").capitalize(),
        state=state,  # type: ignore[arg-type]
        captured_at=captured,
        expires_at=expires,
        exports=0 if captured is None else 1,
        refresh=None if state is CURRENT else "Export again.",
    )


# --- the ranges -----------------------------------------------------------------------


def test_the_trend_range_is_7_30_or_90_days_and_90_by_default() -> None:
    assert read_days("") == HISTORY_DAYS == 90
    assert read_days(" 30 ") == 30 and read_days("7") == 7
    for value in ("45", "ninety", "0", "-7"):
        with pytest.raises(FormError) as refused:
            read_days(value)
        assert refused.value.status_code == 422


def test_the_history_span_is_a_quarter_a_year_or_every_report() -> None:
    assert HISTORY_KEYS == ("90", "365", "all") and read_range("") == DEFAULT_HISTORY
    assert read_range("365") == "365"
    with pytest.raises(FormError):
        read_range("forever")
    now = AS_OF + timedelta(days=1)
    assert history_days("90", [], now) == 90 and history_days("365", [], now) == 365
    # "All" reaches back to the oldest report; without one it is a quarter.
    assert history_days("all", [], now) == HISTORY_DAYS
    assert history_days("all", [point(1, 50, 400), point(1, 60)], now) == 402
    # A day of reports still spans a week, so no date of the axis repeats.
    assert history_days("all", [point(1, 60)], now) == 7


def test_the_dates_of_the_time_axis_divide_the_span_evenly() -> None:
    # Seen on Development at 390px: over three days the middle date of the narrow
    # drawing sat at a third of the axis and ran into the first one.
    now = AS_OF + timedelta(days=1)
    narrow = trend_chart([point(1, 60)], {1: "Alder"}, now, days=3, size=NARROW_CHART)
    assert [x for x, _, _ in narrow.x_ticks] == ["36.0", "170.0", "304.0"]
    wide = trend_chart([point(1, 60)], {1: "Alder"}, now, days=7)
    labels = [label for _, label, _ in wide.x_ticks]
    assert len(set(labels)) == len(labels) == 4


# --- the marks on the score charts ----------------------------------------------------


def documents() -> list[tuple[int, dict[str, object], int]]:
    a = snapshot_document(report_clients.inputs(LIBRARY, "A", AS_OF))
    b = snapshot_document(
        report_clients.inputs(LIBRARY, "B", AS_OF - timedelta(days=10))
    )
    older = snapshot_document(
        report_clients.inputs(LIBRARY, "A", AS_OF - timedelta(days=40))
    )
    return [(1, a, 11), (2, b, 12), (1, older, 10), (3, {"not": "a snapshot"}, 13)]


def test_a_point_knows_the_report_it_opens() -> None:
    points = report_points(documents())
    assert [item.snapshot_id for item in points] == [10, 12, 11]
    assert points[0].path == "clients/1/reports/10"
    # Read without its row (the older two-tuple form), a point opens the list.
    bare = report_points([(owner, document) for owner, document, _ in documents()])
    assert all(item.snapshot_id == 0 for item in bare)
    assert bare[0].path == "clients/1/reports"


def test_every_report_is_a_mark_with_its_values_in_words() -> None:
    names = {1: "Alder and Finch Ltd", 2: "Birch Logistics"}
    chart = trend_chart(report_points(documents()), names, AS_OF + timedelta(days=1))
    alder, birch = chart.lines
    assert len(alder.marks) == len(alder.rows) == 2 and len(birch.marks) == 1
    last = alder.marks[-1]
    assert (last.x, last.y) == (alder.last_x, alder.last_y)
    assert last.path == "clients/1/reports/11"
    assert (last.day, last.score, last.band) == alder.rows[-1]
    words = f"{last.day}: score {last.score}, {last.band}"
    assert last.tip == f"Alder and Finch Ltd\n{words}"
    # Thin evidence is a lower bound, never read as a score.
    thin = ReportPoint(1, AS_OF, Fraction(12), "Insufficient evidence", True, 1, 1, 5)
    only = trend_chart([thin], names, AS_OF + timedelta(hours=1)).lines[0].marks[0]
    assert "lower bound 12.0, Insufficient evidence" in only.tip


def test_a_sparkline_mark_names_its_week_and_its_value() -> None:
    weeks = [
        WeekPoint(AS_OF - timedelta(days=7 * back), 1, None, None)
        for back in range(2, -1, -1)
    ]
    marks = spark_marks([1, None, 3], weeks, "clients")
    assert [mark.value for mark in marks] == ["1", "3"]
    assert marks[0].tip == "Week ending 2026-10-03\n1 clients"
    assert marks[1].tip == "Week ending 2026-10-17\n3 clients"
    assert spark_marks([None, 2], weeks, "clients") == ()


# --- the age of every export ----------------------------------------------------------


def test_the_age_bars_share_one_scale_and_mark_the_stale_date() -> None:
    rows = [
        source("backup-export", EXPIRED, 100),
        source("device-inventory", CURRENT, 2),
        source("network-export", MISSING, None),
        source("training-csv", STALE, 95, 60),
    ]
    bars = age_bars(rows, NOW)
    assert [bar.code for bar in bars] == [row.code for row in rows]
    backup, devices, network, training = bars
    # The scale is twice the longest window (180 days), where an export counts for
    # nothing: every stale mark sits at most halfway, never on the rounded end.
    assert (backup.age_days, backup.stale_days) == (100, 90)
    assert (backup.width, backup.mark) == ("55.56", "50.00")
    assert backup.words == "100 days old, stale after 90 days"
    assert backup.tip.split("\n") == [
        "Backup export",
        "Expired",
        "Newest export 2026-07-09, 100 days old",
        "Stale after 90 days: 2026-10-07",
    ]
    assert (devices.width, devices.mark) == ("1.11", "50.00")
    assert (training.width, training.mark) == ("52.78", "33.33")
    assert training.state is STALE and devices.imported
    assert not network.imported and network.words == NEVER_IMPORTED
    assert (network.width, network.mark) == ("0", "")
    assert network.tip.endswith("No export has been imported.")


def test_the_stale_mark_stays_inside_the_track() -> None:
    # One current source alone: its window is the longest, and its mark must not
    # land on the end of the track, where the rounded bar would clip it.
    (alone,) = age_bars([source("leavers-csv", CURRENT, 1, 35)], NOW)
    assert (alone.width, alone.mark) == ("1.43", "50.00")
    # An export older than twice every window sets the scale and fills its track.
    rows = [source("a", EXPIRED, 300), source("b", CURRENT, 3, 30)]
    old, fresh = age_bars(rows, NOW)
    assert (old.width, old.mark) == ("100.00", "30.00")
    assert (fresh.width, fresh.mark) == ("1.00", "10.00")


def test_an_export_captured_today_and_one_without_a_window() -> None:
    rows = [source("a", CURRENT, 0), source("b", CURRENT, 3, None)]
    today, free = age_bars(rows, NOW)
    assert today.words == "captured today, stale after 90 days"
    assert free.words == "3 days old" and free.mark == "" and free.stale_days is None
    assert isinstance(free, AgeBar)


# --- the clients by band --------------------------------------------------------------


def card(number: int, name: str, report: object = None) -> ClientCard:
    return ClientCard(number, name, 0, None, None, report)  # type: ignore[arg-type]


def test_the_bands_are_counted_in_the_order_of_the_model() -> None:
    reports = {
        name: last_report_of(report_clients.inputs(LIBRARY, name, AS_OF))
        for name in ("A", "B", "C")
    }
    cards = [
        card(1, "Alder", reports["A"]),
        card(2, "Birch", reports["B"]),
        card(3, "Cedar", reports["C"]),
        card(4, "Dune"),
    ]
    counts = band_counts(cards)
    assert [item.key for item in counts] == [*BAND_KEYS, NO_REPORT_KEY]
    assert BAND_KEYS == ("strong", "good", "fair", "weak", "critical", "insufficient")
    assert sum(item.count for item in counts) == 4
    by_key = {item.key: item for item in counts}
    none = by_key[NO_REPORT_KEY]
    assert (none.count, none.name) == (1, "No report yet")
    for report in reports.values():
        assert by_key[band_key(report.band)].count >= 1
    # The fullest band fills its track; the others are read against it.
    fullest = max(item.count for item in counts)
    for item in counts:
        assert (item.width == "100.00") == (item.count == fullest), item
        assert (item.width == "0.00") == (item.count == 0), item
    assert none.tip == "No report yet\n1 client"
    assert band_counts([]) and all(item.count == 0 for item in band_counts([]))


def test_the_band_filter_keeps_the_clients_of_one_band() -> None:
    report = last_report_of(report_clients.inputs(LIBRARY, "A", AS_OF))
    with_report = card(1, "Alder", report)
    without = card(2, "Dune")
    chosen = ListQuery(band=band_key(report.band))
    assert matches(with_report, chosen) and not matches(without, chosen)
    none = ListQuery(band=NO_REPORT_KEY)
    assert matches(without, none) and not matches(with_report, none)
    assert matches(with_report, ListQuery()) and matches(without, ListQuery())
    assert chosen.params() == f"?band={chosen.band}"
    assert read_band("") == "" and read_band(" none ") == "none"
    with pytest.raises(FormError):
        read_band("purple")


# --- the templates, the script and the stylesheet ------------------------------------


def test_the_chart_script_is_linked_plain_and_first_party() -> None:
    script = '<script src="/static/js/charts.js?v={{ asset_version }}" defer></script>'
    assert script in BASE and BASE.index("revrook.js") < BASE.index("charts.js")
    sheet = 'href="/static/css/charts.css?v={{ asset_version }}">'
    assert sheet in BASE and BASE.index("revrook-retest.css") < BASE.index(sheet)
    assert "js/charts.js" in ASSET_FILES and "css/charts.css" in ASSET_FILES
    assert '"use strict"' in SCRIPT
    for forbidden in ("eval(", "http", "fetch(", "XMLHttpRequest", "innerHTML"):
        assert forbidden not in SCRIPT, forbidden
    # The tooltip is placed through the CSSOM, never an inline style attribute.
    assert "box.style.left" in SCRIPT and 'setAttribute("style"' not in SCRIPT
    assert 'closest(node, "[data-tip]")' in SCRIPT
    assert 'if (event.key === "Escape")' in SCRIPT
    # Left and Right only walk the marks: Up and Down keep scrolling the page
    # while a mark or a sparkline has the focus (THE-867, low 3).
    assert 'var NEXT_KEYS = ["ArrowRight"];' in SCRIPT and '"Home"' in SCRIPT
    assert 'var PREVIOUS_KEYS = ["ArrowLeft"];' in SCRIPT
    assert "ArrowUp" not in SCRIPT and "ArrowDown" not in SCRIPT
    assert 'button.setAttribute("aria-pressed", "true");' in SCRIPT
    assert "window.history.replaceState(" in SCRIPT
    ajax = 'window.htmx.ajax("GET", rangePending.path, { target: "#" + targetId });'
    assert ajax in SCRIPT
    assert 'document.addEventListener("htmx:afterSwap", swapped);' in SCRIPT
    # A scroll or a resize moves the tooltip with its mark instead of hiding it:
    # a wheel that brings a mark under a still pointer showed the tip and the
    # scroll event hid it at once on Development (THE-850).
    assert 'window.addEventListener("scroll", moveTip, { passive: true });' in SCRIPT
    assert 'window.addEventListener("resize", moveTip);' in SCRIPT
    assert "placeTip(tipFor);" in SCRIPT and "window.scrollX" not in SCRIPT
    # The query of a range is sent once: htmx with a source element would add
    # the values of the form (the pressed button) to the address a second time.
    assert "source: form" not in SCRIPT
    # The answer of a range is read from the request itself, not from the
    # promise: the page's response handling (base.html, htmx-config) swaps a
    # 422 or a 500 body in as an answer, which put the refusal where the chart
    # was on Development (THE-867, low 4). Only a success is swapped in; any
    # other status, or no answer, leaves for the page with that range and the
    # address is written only after a success.
    assert "pending.then" not in SCRIPT and ".then(" not in SCRIPT
    assert 'document.addEventListener("htmx:beforeSwap", rangeBeforeSwap);' in SCRIPT
    assert 'document.addEventListener("htmx:afterRequest", rangeAnswered);' in SCRIPT
    assert 'document.addEventListener("htmx:sendError", rangeAnswered);' in SCRIPT
    assert "var status = detail.xhr ? detail.xhr.status : 0;" in SCRIPT
    assert "detail.shouldSwap = false;" in SCRIPT
    refused = 'event.type !== "htmx:afterRequest" || status < 200 || status >= 300'
    assert refused in SCRIPT
    assert "window.location.assign(pending.page);" in SCRIPT
    assert "info.requestPath === rangePending.path" in SCRIPT
    remembered = SCRIPT.index("rememberRange(pending.name, pending.value);")
    assert remembered > SCRIPT.index("window.location.assign(pending.page);")
    # A series switched off stays off through a range swap (THE-867, low 5).
    assert "off: seriesOff(target)" in SCRIPT
    assert "restoreSeriesOff(target, pending.off);" in SCRIPT
    assert 'button.rv-series[aria-pressed="false"]' in SCRIPT


def test_the_score_chart_is_a_group_of_report_links_with_a_table() -> None:
    assert 'role="group" aria-labelledby="{{ title_id }}' in CHART
    assert "data-roving" in CHART
    assert 'role="img"' not in CHART
    link = '<a class="rv-mark" href="/{{ mark.path }}" data-tip="{{ mark.tip }}">'
    assert link in CHART and "<title>{{ mark.tip }}</title>" in CHART
    assert '<g class="rv-chart-line" data-series="{{ line.client_id }}">' in CHART
    assert '<tr data-series="{{ line.client_id }}">' in CHART
    assert '<a href="/{{ mark.path }}">{{ mark.day }}</a>' in CHART
    assert '<div class="rv-table-scroll">\n<table class="rv-table-cards' in CHART
    form = '<form class="rv-range" method="get" action="/{{ action }}"'
    assert form in CHART and 'data-fragment="{{ fragment }}"' in CHART
    assert 'name="{{ name }}" value="{{ value }}" aria-pressed=' in CHART


def test_the_home_and_the_builder_hold_the_cards_the_fragments_fill() -> None:
    assert '<div id="trend-body">\n{% include "_trend_chart.html" %}' in HOME
    trend_form = 'c.range_form("", "/charts/trend", "trend-body", "days", ranges, days'
    assert trend_form in TREND
    assert "{% for chart in (trend, trend_narrow) %}" in TREND
    assert '<li data-series="{{ line.client_id }}">' in TREND
    assert 'id="trend-empty"' in TREND
    assert "No reports in the last {{ days }} days" in TREND
    assert '<div id="history-body">\n{% include "_history_chart.html" %}' in REPORTS
    history_form = '"/clients/" ~ client_id ~ "/charts/history", "history-body", "span"'
    assert history_form in HISTORY
    assert "{% for chart in (history, history_narrow) %}" in HISTORY
    assert 'id="history-empty"' in HISTORY


def test_the_sparklines_and_the_bars_carry_their_words_and_their_links() -> None:
    spark = 'role="img" tabindex="0" aria-label="{{ stat.spark_label }}" data-spark'
    assert spark in HOME
    mark = '<circle class="rv-spark-mark" cx="{{ mark.x }}" cy="{{ mark.y }}" r="4"'
    assert mark in HOME
    # The sparkline; the score bars that replaced the rings are in _drivers.html.
    assert HOME.count('role="img"') == 1
    assert 'role="group" aria-label="{{ bar.name }} by status" data-roving' in HOME
    assert 'href="#domain-row-{{ bar.code }}"' in HOME
    assert '<tr id="domain-row-{{ bar.code }}" tabindex="-1">' in HOME
    assert 'aria-hidden="true" focusable="false">{% for seg' not in HOME
    # The overview drills into the checklist by status, and by domain and status.
    status = 'href="/clients/{{ client_id }}/checklist?status={{ seg.label.key }}"'
    assert status in OVERVIEW
    both = 'checklist?domain={{ bar.code }}&amp;status={{ seg.label.key }}"'
    assert both in OVERVIEW and OVERVIEW.count("data-roving") == 2
    assert 'aria-hidden="true" focusable="false">{% for seg' not in OVERVIEW
    # The evidence page: one bar per source on one scale, the stale mark, a row.
    assert 'id="ages"' in EVIDENCE and '<ul class="rv-ages">' in EVIDENCE
    assert 'href="#source-{{ bar.code }}" data-tip="{{ bar.tip }}"' in EVIDENCE
    assert '<rect class="rv-age-mark" x="{{ bar.mark }}"' in EVIDENCE
    assert '<tr id="source-{{ row.code }}" tabindex="-1">' in EVIDENCE
    assert "s.status(state)" in EVIDENCE
    # The clients list: a band is a link that narrows the list.
    assert 'id="bands"' in LIST and 'data-tip="{{ item.tip }}"' in LIST
    assert 'href="/clients{{ query.params(band=item.key, page=1) }}"' in LIST
    assert '<input type="hidden" name="band" value="{{ query.band }}">' in LIST
    # The checklist names a narrowing and takes it away.
    assert 'id="show-narrowed" class="rv-chip rv-chip-narrowed"' in CHECKLIST
    # Every chip keeps the other choices of the list (ChecklistQuery, THE-1188).
    assert "checklist{{ query.params(show='flagged') }}" in CHECKLIST
    assert "checklist{{ query.params(show='all') }}" in CHECKLIST
    assert "checklist{{ query.params(domain='', status='') }}" in CHECKLIST
    assert "No control matches" in CHECKLIST


def test_the_chart_rules_use_role_tokens_and_short_motion() -> None:
    for selector in (
        ".rv-tip {",
        ".rv-tip.is-shown {",
        "main .rv-range button.rv-range-choice {",
        ".rv-chart-enter {",
        "@keyframes rv-chart-in {",
        'html[data-charts="ready"] .rv-chart-legend {',
        ".rv-chart a.rv-mark:focus-visible circle {",
        ".rv-spark-mark.is-active {",
        ".rv-age-mark {",
        ".rv-band-fill {",
        "main a.rv-chip-narrowed {",
    ):
        assert selector in CSS, selector
    # Seen on Development: Pico's square marker on every li showed beside each
    # band of the clients list, so the band item itself takes none.
    band = re.search(r"\n\.rv-bands > li\.rv-band \{([^}]*)\}", CSS)
    assert band is not None and "list-style: none;" in band.group(1)
    # On a phone the count sits beside the name on the first row and the bar
    # takes the second, each placed by name: left to the auto placement, the
    # count (after the bar in the markup) sat on a row of its own under the bar
    # at 390 px on Development.
    narrow = CSS[CSS.index("@media (max-width: 599px) {") :]
    assert "  .rv-band-count {\n    grid-row: 1;\n    grid-column: 2;\n  }" in narrow
    bar = "  .rv-bands .rv-band-bar {\n    grid-row: 2;\n    grid-column: 1 / -1;\n  }"
    assert bar in narrow
    # And the history card, as wide as the page, drew its axis text at 20px.
    history = re.search(r"\n\.rv-history \.rv-chart-wide \{([^}]*)\}", CSS)
    assert history is not None and "max-width: 640px;" in history.group(1)
    plain = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
    for duration in re.findall(r"(\d+)ms", plain):
        assert int(duration) <= 200, duration
    # Role tokens only: no hex colour, and nothing loaded from outside.
    assert "#" not in plain
    for forbidden in ("url(", "@import", "http"):
        assert forbidden not in plain, forbidden
    sizes = set(re.findall(r"(?<![-\w])font-size:\s*([^;]+);", plain))
    assert sizes <= {"12px", "13px", "14px"}, sizes


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_every_text_rule_of_the_chart_stylesheet_declares_a_checked_pair(
    theme: str,
) -> None:
    # The convention of revrook.css, read with the parser of its contrast test:
    # a rule that colours text names its background, and the pair reaches 4.5.
    from test_brand_contrast import THEMES, contrast_ratio, parse_rules, resolve

    variables = THEMES[theme]
    checked = 0
    for selector, declarations in parse_rules(CSS):
        if "color" not in declarations:
            continue
        assert "background-color" in declarations, selector
        text = resolve(declarations["color"], variables)
        background = resolve(declarations["background-color"], variables)
        assert text and background, selector
        ratio = contrast_ratio(text, background)
        assert ratio >= 4.5, f"{selector} ({theme}): {ratio:.2f}"
        checked += 1
    assert checked >= 8


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_the_tooltip_and_the_new_marks_reach_their_contrast(theme: str) -> None:
    # The parsed themes and the ratio of the contrast test, read where they live.
    from test_brand_contrast import THEMES, contrast_ratio, resolve

    variables = THEMES[theme]
    words = resolve("var(--rv-white)", variables)
    rail = resolve("var(--rv-rail)", variables)
    assert words and rail and contrast_ratio(words, rail) >= 4.5
    surface = resolve("var(--rv-surface)", variables)
    for token in ("--rv-text-secondary", "--rv-primary"):
        mark = resolve(f"var({token})", variables)
        assert mark and surface and contrast_ratio(mark, surface) >= 3.0, token


# --- the routes --------------------------------------------------------------------


async def test_a_fragment_needs_a_session_and_is_a_fragment_only_for_htmx(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    for path in ("/charts/trend", "/clients/1/charts/history"):
        plain = await ui_browser.get(path)
        assert plain.status_code == 303 and plain.headers["location"] == "/login"
        htmx = await ui_browser.get(path, headers={"HX-Request": "true"})
        assert htmx.status_code == 200 and htmx.headers["HX-Redirect"] == "/login"
    assert (await login(ui_browser)).status_code == 303
    # Asked for as a page, the fragment sends the person to the page that holds it.
    page = await ui_browser.get("/charts/trend", params={"days": "30"})
    assert page.status_code == 303 and page.headers["location"] == "/?days=30"
    fragment = await ui_browser.get(
        "/charts/trend", params={"days": "30"}, headers={"HX-Request": "true"}
    )
    assert fragment.status_code == 200
    assert fragment.headers["cache-control"] == "no-store, no-transform"
    assert "default-src 'self'" in fragment.headers["content-security-policy"]
    assert "<html" not in fragment.text and 'class="rv-range"' in fragment.text
    assert PRESSED.findall(fragment.text) == [("days", "30")]
    assert 'id="trend-empty"' in fragment.text
    refused = await ui_browser.get(
        "/charts/trend", params={"days": "45"}, headers={"HX-Request": "true"}
    )
    assert refused.status_code == 422
    missing = await ui_browser.get(
        "/clients/424242/charts/history", headers={"HX-Request": "true"}
    )
    assert missing.status_code == 404


async def test_home_draws_the_range_asked_for_and_marks_every_report(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    week = await ui_browser.get("/", params={"days": "7"})
    assert week.status_code == 200 and structure_problems(week.text) == []
    assert PRESSED.findall(week.text) == [("days", "7")]
    assert "No reports in the last 7 days" in week.text
    refused = await ui_browser.get("/", params={"days": "12"})
    assert refused.status_code == 422 and "Synthetic" not in refused.text

    report = await make_report(ui_browser, csrf, client_id)
    snapshot_id = report.rsplit("/", 1)[1]
    home = await ui_browser.get("/")
    assert home.status_code == 200 and structure_problems(home.text) == []
    assert PRESSED.findall(home.text) == [("days", "90")]
    expected = f"/clients/{client_id}/reports/{snapshot_id}"
    assert MARK.findall(home.text) == [expected, expected]  # wide and narrow
    assert f'<a href="{expected}">2026-10-17</a>' in home.text
    assert f'<li data-series="{client_id}">' in home.text
    assert 'data-tip="Synthetic Client Ltd\n2026-10-17: ' in home.text
    # The sparklines carry their weeks; the domain bars their segments and rows.
    assert 'class="rv-spark-mark"' in home.text and "Week ending " in home.text
    assert f'href="#domain-row-{DOMAIN.code}"' in home.text
    assert f'<tr id="domain-row-{DOMAIN.code}" tabindex="-1">' in home.text
    fragment = await ui_browser.get(
        "/charts/trend", params={"days": "7"}, headers={"HX-Request": "true"}
    )
    assert fragment.status_code == 200
    assert MARK.findall(fragment.text) == [expected] * 2


async def test_the_builder_draws_the_history_of_the_client_for_a_span(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    address = f"/clients/{client_id}/reports"
    before = await ui_browser.get(address)
    assert before.status_code == 200 and structure_problems(before.text) == []
    assert 'id="history-empty"' in before.text and ">No report yet<" in before.text
    assert PRESSED.findall(before.text) == [("span", "all")]

    report = await make_report(ui_browser, csrf, client_id)
    after = await ui_browser.get(address, params={"span": "365"})
    assert after.status_code == 200 and structure_problems(after.text) == []
    assert PRESSED.findall(after.text) == [("span", "365")]
    assert MARK.findall(after.text) == [report, report]
    assert "Score by report date, 1 report in this span" in after.text
    refused = await ui_browser.get(address, params={"span": "forever"})
    assert refused.status_code == 422
    fragment = await ui_browser.get(
        f"/clients/{client_id}/charts/history",
        params={"span": "90"},
        headers={"HX-Request": "true"},
    )
    assert fragment.status_code == 200 and "<html" not in fragment.text
    assert MARK.findall(fragment.text) == [report, report]
    page = await ui_browser.get(f"/clients/{client_id}/charts/history")
    assert page.status_code == 303
    assert page.headers["location"] == f"{address}?span=all"


async def test_a_segment_narrows_the_checklist_to_a_domain_and_a_status(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    overview = await ui_browser.get(f"/clients/{client_id}")
    assert overview.status_code == 200
    assert f'href="/clients/{client_id}/checklist?status=' in overview.text
    both = f'href="/clients/{client_id}/checklist?domain={DOMAIN.code}&amp;status='
    assert both in overview.text
    address = f"/clients/{client_id}/checklist"
    narrowed = await ui_browser.get(address, params={"domain": DOMAIN.code})
    assert narrowed.status_code == 200 and structure_problems(narrowed.text) == []
    rows = narrowed.text.count('<th scope="row"><a class="rv-control-link"')
    assert rows == len(LIBRARY.in_domain(DOMAIN.code))
    chip = f'id="show-narrowed" class="rv-chip rv-chip-narrowed" href="{address}"'
    assert chip in narrowed.text and f">{DOMAIN.name} <span" in narrowed.text
    kept = f'id="show-all" class="rv-chip" href="{address}?domain={DOMAIN.code}"'
    assert kept in narrowed.text
    both = await ui_browser.get(
        address, params={"domain": DOMAIN.code, "status": "protected", "show": "all"}
    )
    assert both.status_code == 200 and structure_problems(both.text) == []
    assert f">{DOMAIN.name}, protected <span" in both.text
    shown = both.text.count('<th scope="row"><a class="rv-control-link"')
    assert shown <= rows
    if shown == 0:
        assert "No control matches" in both.text
    for query in ({"domain": "XXX"}, {"status": "blue"}, {"domain": "a;b"}):
        refused = await ui_browser.get(address, params=query)
        assert refused.status_code == 422, query


async def test_the_evidence_page_draws_the_age_of_every_export(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get(f"/clients/{client_id}/evidence")
    assert page.status_code == 200 and structure_problems(page.text) == []
    assert 'id="ages"' in page.text and '<ul class="rv-ages">' in page.text
    # The backup export of the seeded client is 100 days old and expired.
    assert 'id="age-backup-export"' in page.text
    assert "100 days old, stale after " in page.text
    assert 'href="#source-backup-export"' in page.text
    assert '<tr id="source-backup-export" tabindex="-1">' in page.text
    assert 'class="rv-seg-not-protected" x="0" y="0" width="' in page.text
    assert '<rect class="rv-age-mark" x="' in page.text
    assert page.text.count(NEVER_IMPORTED) >= 1
    assert "Goes stale" in page.text


async def test_the_list_counts_the_bands_and_narrows_to_one(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    other_id = await seed_client(db_engine, ui_ctx, "Other Client Ltd")
    await make_report(ui_browser, csrf, client_id)
    page = await ui_browser.get("/clients")
    assert page.status_code == 200 and structure_problems(page.text) == []
    assert 'id="bands"' in page.text
    assert '<span class="rv-band-name">No report yet</span>' in page.text
    assert 'href="/clients?band=none"' in page.text
    none = await ui_browser.get("/clients", params={"band": "none"})
    assert none.status_code == 200 and structure_problems(none.text) == []
    assert f'href="/clients/{other_id}"' in none.text
    assert f'href="/clients/{client_id}">' not in none.text
    assert 'href="/clients?band=none" data-tip="No report yet\n1 client"' in none.text
    assert 'aria-current="true"' in none.text and ">Show every band</a>" in none.text
    assert ", no report yet, by name" in none.text
    refused = await ui_browser.get("/clients", params={"band": "purple"})
    assert refused.status_code == 422
