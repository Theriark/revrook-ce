"""The route revamp (THE-1360, REV-323), drawn through the application.

tests/test_revamp.py and tests/test_revamp_rendered.py cover the shared layer and
Home; these cover the pages of one client after the overview (exceptions, the
report builder, preview and export, the export history), the administration
(settings, system, the glossary), the client overview under the band, and the
keep panel of Home when no scene stands beside the gauge. The review horizon of
the exceptions register is tested as a pure function as well. The pages need
PostgreSQL (DATABASE_URL) and are skipped without it.
"""

import re
from datetime import date, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evidence.service import EvidenceContext
from app.ui.brand import STATIC_DIR
from app.ui.horizon import (
    HORIZON_AXIS,
    HORIZON_DAYS,
    HORIZON_LEVELS,
    HORIZON_WIDTH,
    MARK_GAP,
    MARK_HEIGHT,
    MARK_STEP,
    MARK_WIDTH,
    OVERDUE_GUTTER,
    Due,
    review_horizon,
)
from helpers import NOW
from html_structure import structure_problems
from ui_helpers import exported_id, make_report, post_export, seed_client, sign_in

SHEET = (STATIC_DIR / "css/revamp.css").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", SHEET, flags=re.DOTALL)
TODAY = NOW.date()
MARK = re.compile(
    r'<rect class="rv-horizon-mark rv-horizon-([a-z]+)" x="([0-9.]+)" y="([0-9.]+)"'
)
TERM_LINK = re.compile(r'<a href="#(term-[a-z-]+)">')
TERM_ID = re.compile(r'<div id="(term-[a-z-]+)"')
OVERVIEW_TAB = re.compile(
    r'<a class="rv-nav-link" href="/clients/\d+" aria-current="page">'
)
BODY_MINIMUM = 4.5
LONG_NAME = "Very Long Client Name Holdings and Partners International"


def due(control: str, days: int, closed: bool = False) -> Due:
    return Due(control, TODAY + timedelta(days=days), days < 0, closed)


def tokens(selector: str) -> dict[str, str]:
    """The colour tokens declared by the first rule of revamp.css with `selector`."""
    start = CSS.index(selector + " {")
    body = CSS[CSS.index("{", start) + 1 : CSS.index("}", start)]
    found = re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", body)
    return {name: value.lower() for name, value in found}


def luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# --- the review horizon, as a function ---------------------------------------------


def test_the_horizon_stands_each_open_exception_at_its_review_date() -> None:
    rows = [
        due("PC-ACC-01", -40),
        due("PC-ACC-02", -3),
        due("PC-BCK-01", 7),
        due("PC-BCK-02", 7),
        due("PC-END-01", 200),
        due("PC-END-02", HORIZON_DAYS + 30),
        due("PC-NET-01", 20, closed=True),
    ]
    horizon = review_horizon(rows, TODAY)
    assert (horizon.overdue, horizon.soon, horizon.within_year) == (2, 2, 3)
    assert horizon.beyond_year == 1
    # A closed exception and one more than a year away are not drawn
    assert [mark.control_id for mark in horizon.marks] == [
        "PC-ACC-01",
        "PC-ACC-02",
        "PC-BCK-01",
        "PC-BCK-02",
        "PC-END-01",
    ]
    # Past their date: before the line of today, one above the other
    overdue = [mark for mark in horizon.marks if mark.state == "overdue"]
    assert all(float(mark.x) + MARK_WIDTH <= OVERDUE_GUTTER for mark in overdue)
    assert [mark.y for mark in overdue] == [
        str(HORIZON_AXIS - MARK_HEIGHT),
        str(HORIZON_AXIS - MARK_HEIGHT - MARK_STEP),
    ]
    first, second, later = horizon.marks[2:]
    assert first.state == second.state == "soon" and later.state == "later"
    assert first.x == second.x and first.y != second.y
    assert OVERDUE_GUTTER < float(first.x) < float(later.x) < HORIZON_WIDTH


def test_the_horizon_names_the_months_ahead_and_caps_a_stack() -> None:
    horizon = review_horizon([due(f"PC-ACC-{n:02d}", 5) for n in range(6)], TODAY)
    lowest = HORIZON_AXIS - MARK_HEIGHT - (HORIZON_LEVELS - 1) * MARK_STEP
    assert min(int(mark.y) for mark in horizon.marks) == lowest >= 0
    assert 11 <= len(horizon.months) <= 12
    xs = [float(x) for x, _ in horizon.months]
    assert xs == sorted(xs) and OVERDUE_GUTTER < xs[0] and xs[-1] < HORIZON_WIDTH
    assert any(label.startswith("Jan ") for _, label in horizon.months)
    assert review_horizon([], TODAY).marks == ()


def test_the_horizon_edges_today_the_last_day_and_the_turn_of_the_year() -> None:
    # THE-1375: the edge dates had no test
    rows = [
        due("PC-ACC-01", 0),
        due("PC-ACC-02", HORIZON_DAYS),
        due("PC-ACC-03", HORIZON_DAYS + 1),
    ]
    horizon = review_horizon(rows, TODAY)
    assert (horizon.soon, horizon.within_year, horizon.beyond_year) == (1, 2, 1)
    today, last = horizon.marks
    # Today stands just after the line of today, the last day at the right edge
    assert float(today.x) == OVERDUE_GUTTER and today.state == "soon"
    assert float(last.x) + MARK_WIDTH == HORIZON_WIDTH and last.state == "later"
    new_year = review_horizon([], date(2027, 1, 1)).months
    assert len(new_year) == 12
    assert new_year[0][1] == "Feb" and new_year[-1][1] == "Jan 2028"
    assert review_horizon([], date(2026, 12, 31)).months[0][1] == "Jan 2027"


def test_merlons_a_few_days_apart_stack_across_a_slot_boundary() -> None:
    # THE-1375: days 9 and 10 fell into neighbouring 12-unit slots and overlapped
    near = review_horizon([due("PC-ACC-01", 9), due("PC-ACC-02", 10)], TODAY)
    first, second = near.marks
    assert abs(float(first.x) - float(second.x)) < MARK_WIDTH + MARK_GAP
    assert first.y != second.y
    apart = review_horizon([due("PC-ACC-01", 9), due("PC-ACC-02", 30)], TODAY)
    assert apart.marks[0].y == apart.marks[1].y


# --- the stylesheet ------------------------------------------------------------------


def test_the_keep_panel_is_one_column_without_a_scene() -> None:
    # THE-1355: without WebGL 2 the second column of the panel stayed empty
    scene = '.rv-keep-panel:has(> .rv-scene[data-scene-state="unavailable"]) {'
    assert scene + "\n  grid-template-columns: minmax(0, 1fr);" in CSS
    no_script = CSS.split("@media (scripting: none) {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr);" in no_script
    scenes = (STATIC_DIR / "js/scenes.js").read_text(encoding="utf-8")
    assert 'root.setAttribute("data-scene-state", "unavailable");' in scenes


def test_the_paper_of_the_preview_and_the_cover_reads_in_every_theme() -> None:
    paper = tokens(".rv-sheet-band .rv-sheet")
    for word in ("--rv-text", "--rv-text-secondary", "--rv-link"):
        assert contrast(paper[word], paper["--rv-surface"]) >= BODY_MINIMUM, word
    for key in ("protected", "needs-attention", "not-protected", "not-checked"):
        tint = paper[f"--rv-tint-{key}"]
        assert contrast(paper[f"--rv-status-{key}"], tint) >= BODY_MINIMUM, key
    cover = tokens(".rv-cover")
    for word in ("--rv-paper-ink", "--rv-paper-quiet"):
        assert contrast(cover[word], cover["--rv-paper"]) >= BODY_MINIMUM, word


def test_the_findings_of_the_deployed_check_have_their_rules() -> None:
    # THE-1311 decision ebb42405, from the deployed check of 11e716e0: a faint
    # battlement in the dark theme, a void beyond 1448px, no marker on the folded
    # rule of a control, a checklist of 15753px at 390px
    assert "repeating-linear-gradient(90deg, var(--rv-keep-crest) 0 40px" in CSS
    light, dark = tokens(":root"), tokens(':root[data-theme="dark"]')
    assert light["--rv-keep-crest"] == light["--rv-keep"]
    assert contrast(dark["--rv-keep-crest"], dark["--rv-keep"]) >= 2
    wide = CSS.split("@media (min-width: 1449px) {", 1)[1].split("\n}\n", 1)[0]
    for rule in (
        ".rv-app .rv-content,",
        "margin-inline: auto;",
        "left: -100vw;",
        "border-image-outset: 0 100vw;",
    ):
        assert rule in wide, rule
    assert ".rv-rule-more[open] > summary::before {\n  transform: rotate(90deg);" in CSS
    phone = "main .rv-checklist tbody tr[data-control] {\n    display: flex;"
    assert phone in CSS


def test_the_findings_of_the_check_of_6369873c_have_their_rules() -> None:
    # The deployed check of 6369873c (THE-1360 report rev 3) and THE-1375
    # 1) Pico lays a nav out as one row: the glossary index is a column again
    assert ".rv-glossary-index {\n  display: block;\n}" in CSS
    assert ".rv-glossary-index li {\n  display: block;\n}" in CSS
    # 2) the action of a phone card takes the whole card
    actions = "tbody tr > td.rv-row-actions {\n    grid-column: 1 / -1;"
    assert "main .rv-table-cards " + actions in CSS
    # 3) the horizon on a phone names every second month, larger
    phone = CSS.split("@media (max-width: 599px) {", 1)[1].split("\n}\n", 1)[0]
    assert "font-size: 20px;" in phone
    assert ".rv-horizon-month:nth-of-type(even)," in phone
    # 4) long values keep their words; the kept reports beside the builder in rows
    assert "flex: 1 1 9rem;" in CSS and "text-wrap: balance;" in CSS
    assert ".rv-builder-side .rv-snapshots tbody th {" in CSS
    # (f) the column beside the builder no longer sticks
    assert re.search(r"\.rv-builder[a-z-]* \{[^}]*sticky", CSS) is None
    # (g) the paper of the preview resets every Pico colour it reads
    paper = CSS.split(".rv-sheet-band .rv-sheet {", 1)[1].split("}", 1)[0]
    for name in ("h4-color", "muted-border-color", "table-border-color"):
        assert f"--pico-{name}:" in paper, name


# --- the pages ----------------------------------------------------------------------


async def test_the_exceptions_register_opens_with_its_horizon(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    empty = await ui_browser.get(f"/clients/{client_id}/exceptions")
    assert empty.status_code == 200 and 'id="review-horizon"' not in empty.text
    for control, days in (("PC-ACC-01", 12), ("PC-BCK-01", 150)):
        added = await ui_browser.post(
            f"/clients/{client_id}/exceptions",
            data={
                "csrf_token": csrf,
                "control_id": control,
                "owner": "Synthetic Owner",
                "reason": "Accepted for the test.",
                "review_date": (TODAY + timedelta(days=days)).isoformat(),
            },
        )
        assert added.status_code == 303, added.text
    page = await ui_browser.get(f"/clients/{client_id}/exceptions")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    # The horizon stands between the verdict and the register
    assert html.index('id="exceptions-status"') < html.index('id="review-horizon"')
    assert html.index('id="review-horizon"') < html.index('<table id="exceptions"')
    marks = MARK.findall(html)
    assert [state for state, _, _ in marks] == ["soon", "later"]
    assert float(marks[0][1]) < float(marks[1][1])
    assert "1 due in the next 30 days. 2 due within a year." in html
    assert '<span class="rv-review-when">in 12 days</span>' in html
    assert '<span class="rv-review-when">in 150 days</span>' in html


async def test_the_builder_puts_the_kept_reports_beside_its_steps(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)
    builder = await ui_browser.get(f"/clients/{client_id}/reports")
    html = builder.text
    assert builder.status_code == 200 and structure_problems(html) == []
    steps = html.index('<div class="rv-builder-steps">')
    side = html.index('<div class="rv-builder-side">')
    assert steps < html.index('id="step-make"') < side
    assert side < html.index('<table id="snapshots"') < html.index('id="history"')
    preview = await ui_browser.get(report)
    assert preview.status_code == 200 and structure_problems(preview.text) == []
    assert '<div class="rv-sheet-band">' in preview.text
    made = await post_export(ui_browser, csrf, report, "qbr")
    assert made.status_code == 303 and exported_id(made) > 0
    exports = await ui_browser.get(f"/clients/{client_id}/exports")
    html = exports.text
    assert exports.status_code == 200 and structure_problems(html) == []
    assert 'id="exports-ledger"' in html and "1 kept file</span>" in html
    digest = re.search(r'<code class="rv-digest">([0-9a-f]{64})</code>', html)
    assert digest is not None
    seal = f'<span class="rv-seal" aria-hidden="true">{digest.group(1)[:8]}</span>'
    assert seal in html


async def test_the_overview_renders_under_the_band_and_its_tabs(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    # THE-1356: row 7 of the THE-1313 table counted the overview as rendered by a
    # test; only the checklist and the control page were
    await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    page = await ui_browser.get(f"/clients/{client_id}")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    header = html.index('<div class="rv-page-header rv-client-header">')
    tabs = html.index('<div class="rv-tabs-strip">')
    assert header < tabs < html.index('id="period-picker"')
    assert html.index('id="period-picker"') < html.index('id="posture"')
    assert OVERVIEW_TAB.search(html) is not None
    # The keep scene of the overview stands in the domains card, over its bars
    assert html.index('id="keep-scene"') < html.index('id="domains-list"')


async def test_the_administration_pages_carry_their_own_layout(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await make_report(ui_browser, csrf, client_id)
    settings = await ui_browser.get("/settings")
    html = settings.text
    assert settings.status_code == 200 and structure_problems(html) == []
    assert '<p class="rv-cover-name">Synthetic MSP Ltd</p>' in html
    weights = html.split('<table id="weights"', 1)[1].split("</table>", 1)[0]
    courses = weights.count('<svg class="rv-course"')
    assert courses == weights.count('<th scope="row">') > 0
    system = await ui_browser.get("/system")
    assert system.status_code == 200 and structure_problems(system.text) == []
    assert '<section class="rv-verdict" id="worker"' in system.text
    glossary = await ui_browser.get("/glossary")
    html = glossary.text
    assert glossary.status_code == 200 and structure_problems(html) == []
    links, ids = TERM_LINK.findall(html), TERM_ID.findall(html)
    assert len(links) == len(ids) == 14 and links == ids
    assert html.index('id="glossary-index"') < html.index('<dl id="glossary"')


async def test_home_keeps_the_scene_a_child_of_the_keep_panel(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    # The one-column rule reads the state of the stage as a child of the panel
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    await make_report(ui_browser, csrf, client_id)
    html = (await ui_browser.get("/")).text
    panel = html.split('<div class="rv-keep rv-keep-panel" id="keep-panel">', 1)[1]
    gauge = panel.index('id="portfolio-gauge"')
    assert gauge < panel.index('<div class="rv-scene" id="rookery-scene"')


async def test_a_shortened_chart_label_carries_the_whole_name(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    # THE-1355/1376: a name longer than two label lines ends in "..."; pointing at
    # the label shows the whole name (its title), as the legend and the table do
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx, LONG_NAME)
    await make_report(ui_browser, csrf, client_id)
    page = await ui_browser.get("/")
    html = page.text
    assert page.status_code == 200 and structure_problems(html) == []
    assert f"<title>{LONG_NAME}</title><tspan" in html
    label = html.split(f"<title>{LONG_NAME}</title>", 1)[1].split("</text>", 1)[0]
    assert label.count("<tspan") == 2 and "...</tspan>" in label
