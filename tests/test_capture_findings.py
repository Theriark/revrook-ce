"""The findings of the documentation captures of d0a2e9fe (THE-1487, REV-344).

Capturing the guides on Development d0a2e9fe (THE-1482) found five small defects of
the stylesheet and one question about the data. The rules that answer F2 to F5 are
the last block of app/static/css/revamp.css, F1 is in bulk-actions.css (tested with
the rest of the bulk actions), and these tests read each rule, check that the
markup it is written for still renders, and pin the answer to O6: the score chart
of the report builder ends its time axis today, so its last mark stands at the date
of the newest report, a few days short of the right edge, and that is the data, not
a fault of the drawing. No database: the stylesheet and the templates are read as
files, the shell is rendered through the application's environment, and the chart
is laid out as a pure function.
"""

import re
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

from app.reports.view import iso_date
from app.ui.auth import templates
from app.ui.brand import STATIC_DIR
from app.ui.charts import history_days
from app.ui.dashboard import ReportPoint, trend_chart
from tools.score_inputs import AS_OF

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app/ui/templates"
CSS = (STATIC_DIR / "css/revamp.css").read_text(encoding="utf-8")
SECTION = "Findings of the documentation captures of d0a2e9fe (THE-1487)"
PAGE = """{% extends "base.html" %}{% block content %}
{% include "_client_nav.html" %}{% endblock %}"""
FOLDED_RAIL = "(min-width: 1273px)"
WIDE = "(min-width: 1024px)"
TABLET = "(min-width: 768px) and (max-width: 1079px)"


def new_rules() -> list[tuple[str, str, str]]:
    """(media query or "", selector, declarations) of every rule of the block,
    which ends where the next titled block of the sheet begins."""
    block = CSS.split(SECTION, 1)[1].split("*/", 1)[1]
    block = re.split(r"/\* -{6,} ", block, maxsplit=1)[0]
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
    rules = []
    for media, body in re.findall(r"@media ([^{]+)\{(.*?)\n\}", block, re.DOTALL):
        for selectors, declarations in re.findall(r"([^{}]+)\{([^}]*)\}", body):
            for selector in selectors.split(","):
                rules.append((media.strip(), selector.strip(), declarations))
    plain = re.sub(r"@media [^{]+\{.*?\n\}", "", block, flags=re.DOTALL)
    for selectors, declarations in re.findall(r"([^{}]+)\{([^}]*)\}", plain):
        for selector in selectors.split(","):
            rules.append(("", selector.strip(), declarations))
    return rules


def rules_of(media: str) -> dict[str, str]:
    return {selector: body for where, selector, body in new_rules() if where == media}


def shell(rail: str) -> str:
    return templates.env.from_string(PAGE).render(
        user=SimpleNamespace(username="revrook-admin"),
        csrf_token="x" * 32,
        title="Overview",
        nav="clients",
        rail=rail,
        client_id=1,
        client_name="Alder Ltd",
        section="overview",
    )


# --- the stylesheet ---------------------------------------------------------------


def test_the_block_draws_with_tokens_only_and_every_rule_is_read() -> None:
    block = CSS.split(SECTION, 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgb\(", block)
    rules = new_rules()
    assert len(rules) == 14, [selector for _, selector, _ in rules]


def test_f2_beside_the_folded_rail_the_content_stands_in_the_middle() -> None:
    # Measured on Development d0a2e9fe at 1440px with the rail folded: the page
    # column was 1368px (72px of rail), the content 1200px at its left, 168px
    # empty at its right. The void appears beyond 1272px (72 + 1200), as beyond
    # 1448px beside the open rail (248 + 1200), and is filled the same way.
    found = rules_of(FOLDED_RAIL)
    for part in (".rv-content", ".rv-topbar-inner"):
        assert "margin-inline: auto;" in found[f'body[data-rail="compact"] {part}']
    footer = found['body[data-rail="compact"] .rv-footer']
    assert "padding-inline: calc((100% - 1200px) / 2 + 32px);" in footer
    # The band and the tabs reach the left edge of the column too
    for part in (".rv-page-header::before", ".rv-problem::before"):
        band = found[f'body[data-rail="compact"] .rv-content > {part}']
        assert "left: -100vw;" in band
    tabs = found['body[data-rail="compact"] .rv-content > .rv-tabs-strip']
    assert "border-image-outset: 0 100vw;" in tabs
    # The same answer the wide window has: the rules beyond 1448px are unchanged
    wide = CSS.split("@media (min-width: 1449px) {", 1)[1].split("\n}", 1)[0]
    centred = ".rv-app .rv-topbar-inner {\n    margin-inline: auto;"
    assert ".rv-app .rv-content,\n  " + centred in wide
    assert "padding-inline: calc((100% - 1200px) / 2 + 32px);" in wide


def test_f2_the_shell_renders_the_folded_rail_the_rules_select() -> None:
    from test_nav_strips import Tree, matches

    html = shell("compact")
    assert '<body class="rv-app" data-rail="compact">' in html
    tree = Tree(html)
    everything = list(tree.root.walk())
    for _, selector, _ in [r for r in new_rules() if r[0] == FOLDED_RAIL]:
        target = re.sub(r"::(before|after)$", "", selector)
        if target.endswith(".rv-problem"):
            continue  # the problem page is rendered by the error handlers alone
        assert any(matches(target, element) for element in everything), selector
    # The rail opened: the body says so and nothing of the block applies
    assert '<body class="rv-app" data-rail="expanded">' in shell("expanded")


def test_f3_in_the_drawer_the_verdict_stacks_its_status_over_two_facts_a_row() -> None:
    # Measured on Development d0a2e9fe at 1440px: the drawer is 608px, the status
    # column 224px, the facts 333px, each of the four 167px wide with 119px for
    # its value, where "11 of 11 (100%)" took two lines.
    found = rules_of(WIDE)
    assert "grid-template-columns: minmax(0, 1fr);" in found[".rv-drawer .rv-verdict"]
    status = found[".rv-drawer .rv-verdict .rv-verdict-status"]
    assert "border-right: 0;" in status
    assert "border-bottom: 1px solid var(--rv-line);" in status
    facts = found[".rv-drawer .rv-verdict .rv-verdict-facts"]
    assert "display: grid;" in facts
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in facts
    # The hairlines of the narrow form: under every fact, and after the first of
    # each row; the page keeps "none" on its last fact, so the sheet names it
    every = found[".rv-drawer .rv-verdict .rv-verdict-facts > div"]
    last = found[".rv-drawer .rv-verdict .rv-verdict-facts > div:last-child"]
    assert every == last and "inset 0 -1px 0 var(--rv-line)" in every
    odd = found[".rv-drawer .rv-verdict .rv-verdict-facts > div:nth-child(odd)"]
    assert "inset -1px 0 0 var(--rv-line), inset 0 -1px 0 var(--rv-line)" in odd
    # The markup: the body of a control, in the drawer and on the page, opens with
    # the verdict of four facts, each a div of the list
    body = (TEMPLATES / "_control_body.html").read_text(encoding="utf-8")
    verdict = body.split('<section class="rv-verdict" id="control-status"', 1)[1]
    verdict = verdict.split("</section>", 1)[0]
    assert '<div class="rv-verdict-status">' in verdict
    assert '<dl class="rv-facts rv-verdict-facts">' in verdict
    assert verdict.count("<div><dt>") == 4
    drawer = (TEMPLATES / "_drawer.html").read_text(encoding="utf-8")
    assert '<dialog class="rv-drawer" id="control-drawer"' in drawer
    fragment = (TEMPLATES / "_control_drawer.html").read_text(encoding="utf-8")
    assert '{% include "_control_body.html" %}' in fragment


def test_f4_a_date_of_the_checklist_is_never_broken_on_a_tablet() -> None:
    # Measured on Development d0a2e9fe at 768px: the column of the date was 82px
    # and "2026-10-23" broke at its hyphens. The retest sheet lets .rv-coverage
    # wrap in this band, and the date shares the class; the date cell is named
    # by its column, which the retest rule is not, so this rule wins.
    found = rules_of(TABLET)
    date = found['main .rv-checklist td[data-label="Evidence dated"]']
    assert date.strip() == "white-space: nowrap;"
    retest = (STATIC_DIR / "css/revrook-retest.css").read_text(encoding="utf-8")
    band = retest.split(f"@media {TABLET} {{", 1)[1].split("\n}", 1)[0]
    assert ".rv-checklist .rv-coverage {\n    white-space: normal;" in band
    checklist = (TEMPLATES / "checklist.html").read_text(encoding="utf-8")
    assert '<table id="checklist" class="rv-checklist">' in checklist
    assert '<td data-label="Evidence dated" class="rv-coverage">' in checklist


def test_f5_the_owner_of_an_exception_breaks_between_words_only() -> None:
    # Measured on Development d0a2e9fe at 1440px: the Owner column was 83px and
    # "Office manager" read "Office manage/r", broken anywhere by the rule of a
    # scrolling table in revrook.css.
    found = rules_of("")
    owner = found['main .rv-exceptions td[data-label="Owner"]']
    assert owner.strip() == "overflow-wrap: break-word;"
    base = (STATIC_DIR / "css/revrook.css").read_text(encoding="utf-8")
    scrolling = re.search(r"\n\.rv-table-scroll td \{([^}]*)\}", base)
    assert scrolling is not None and "overflow-wrap: anywhere;" in scrolling.group(1)
    exceptions = (TEMPLATES / "exceptions.html").read_text(encoding="utf-8")
    scroll = '<div class="rv-table-scroll rv-exceptions-scroll"'
    assert exceptions.index(scroll) < exceptions.index(
        '<table id="exceptions" class="rv-table-cards rv-exceptions">'
    )
    assert '<td data-label="Owner">{{ row.owner }}</td>' in exceptions


# --- O6: the time axis of the score history ends today -----------------------------


def test_o6_the_last_mark_stands_at_its_report_date_and_the_axis_ends_today() -> None:
    # Seen on Development d0a2e9fe: the chart of Seed Tidy Ltd named 2026-10-27
    # at the right end of its axis while its newest report was of 2026-10-23.
    # The span "All reports" runs from the oldest report to now, as the Home trend
    # runs to now, so the last mark stands four days short of the edge: its
    # tooltip, its row in the table and the pack date all say 2026-10-23.
    now = AS_OF

    def report(days_ago: int, score: int, band: str) -> ReportPoint:
        moment = now - timedelta(days=days_ago)
        return ReportPoint(20, moment, Fraction(score), band, False, 25, 14)

    points = [report(64, 17, "Critical"), report(34, 49, "Weak"), report(4, 49, "Weak")]
    days = history_days("all", points, now)
    assert days == 65
    chart = trend_chart(points, {20: "Seed Tidy Ltd (synthetic)"}, now, days=days)
    (line,) = chart.lines
    assert [mark.day for mark in line.marks] == [
        iso_date(now - timedelta(days=64)),
        iso_date(now - timedelta(days=34)),
        iso_date(now - timedelta(days=4)),
    ]
    assert [row[0] for row in line.rows] == [mark.day for mark in line.marks]
    assert chart.x_ticks[-1][1] == iso_date(now)
    assert chart.x_ticks[0][1] == iso_date(points[0].as_of - timedelta(days=1))
    # The last mark is short of the right edge by four days of a 65-day axis
    plot = chart.right - chart.left
    assert abs(chart.right - float(line.marks[-1].x) - plot * 4 / 65) < 0.1
    assert float(line.last_x) == float(line.marks[-1].x)
