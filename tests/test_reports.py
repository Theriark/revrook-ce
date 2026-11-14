"""The two reports of phase 8: golden HTML, the disclaimer, escaping and the claims.

The quarterly review and the insurance evidence pack are rendered from a stored
snapshot of the three worked clients (A, B and C of phase-plan-3). Each must equal its
golden file byte for byte (tests/golden/reports, made by tools/make_report_golden.py).
hypothesis is not in the development lock, so the property test draws its cases with
random.Random and a fixed seed, as tests/test_scoring_properties.py does.
"""

import base64
import random
import re
from dataclasses import replace
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from markupsafe import escape

from app.checks.library import load_library
from app.checks.model import NaReview
from app.exceptions import ExceptionEntry
from app.reports.advice import NEXT_STEPS, REFRESH_EVIDENCE
from app.reports.charts import DIAL_LENGTH, MIX_GAP, WIDTH, dial_dash, segment_widths
from app.reports.completeness import (
    MAX_NAME,
    ExportBlockedError,
    completeness_problems,
    ensure_complete,
)
from app.reports.disclaimer import DISCLAIMER, GENERATED_WITH
from app.reports.render import INSURANCE, KINDS, QBR, render_report
from app.reports.status import NOT_APPLICABLE, NOT_CHECKED, PROTECTED
from app.reports.view import (
    Finding,
    ReportContext,
    ReportError,
    ReportView,
    build_view,
)
from app.scoring.model import ControlInput
from app.scoring.snapshot import parse_snapshot, regenerate, render_snapshot
from app.ui.reports import PREVIEW_POLICY
from tools import make_report_golden, report_clients

LIBRARY = load_library()
ROOT = Path(__file__).resolve().parent.parent
NAMES = tuple(report_clients.NAMES)
EXPECTED_SCORES = {"A": "89.5", "B": "45.7", "C": "49.0"}
HOSTILE = "<script>alert(\"x\")</script> & 'quoted' <img src=x onerror=y>"
SECTION = re.compile(r'<section class="page[^"]*" id="([^"]+)".*?</section>', re.DOTALL)
CASES = 500
SEED = 20261019


def view_of(name: str, context: ReportContext | None = None) -> ReportView:
    return build_view(
        report_clients.snapshot_bytes(LIBRARY, name),
        LIBRARY,
        context or report_clients.context_for(name),
        report_clients.previous_bytes(LIBRARY, name),
    )


def html_of(kind: str, name: str, context: ReportContext | None = None) -> str:
    return render_report(kind, view_of(name, context)).decode("utf-8")


# --- golden files ---------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("kind", KINDS)
def test_a_report_of_a_worked_client_equals_its_golden_file(
    kind: str, name: str
) -> None:
    golden = make_report_golden.golden_path(kind, name)
    made = make_report_golden.golden_html(LIBRARY, kind, name)
    assert made == golden.read_bytes(), (
        f"{golden.name} differs; run tools/make_report_golden.py only if the report "
        "was meant to change, and read the diff of the golden files"
    )


def test_there_is_a_golden_file_for_every_kind_and_client_and_no_other() -> None:
    expected = {
        make_report_golden.golden_path(kind, name).name
        for kind in KINDS
        for name in NAMES
    }
    found = {path.name for path in make_report_golden.GOLDEN_DIR.glob("*.html")}
    assert found == expected


@pytest.mark.parametrize("name", NAMES)
def test_the_qbr_prints_the_score_of_the_worked_client(name: str) -> None:
    text = html_of(QBR, name)
    assert f"<dd>{EXPECTED_SCORES[name]} out of 100</dd>" in text


def test_a_capped_score_says_which_gate_holds_it() -> None:
    text = html_of(QBR, "C")
    assert "PC-ACC-02" in text and "is held at 49" in text


# --- the disclaimer and the brand -----------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("kind", KINDS)
def test_every_page_has_the_disclaimer_and_the_last_has_it_in_full(
    kind: str, name: str
) -> None:
    text = html_of(kind, name)
    pages = SECTION.findall(text)
    sections = [match.group(0) for match in SECTION.finditer(text)]
    assert len(pages) >= 4 and pages[0] == "cover" and pages[-1] == "notice"
    for page_id, section in zip(pages, sections, strict=True):
        footer = section.split('<footer class="page-footer">')[-1]
        assert str(escape(DISCLAIMER)) in footer, page_id
        assert GENERATED_WITH in footer, page_id
    assert 'class="disclaimer-full"' in sections[-1]
    assert text.count('class="disclaimer"') == len(pages)


def test_the_insurance_pack_has_a_sign_off_line_on_its_last_page() -> None:
    last = SECTION.findall(html_of(INSURANCE, "A"))[-1]
    assert last == "notice"
    assert "Client sign-off" in html_of(INSURANCE, "A")
    assert "Client sign-off" not in html_of(QBR, "A")


def test_a_report_carries_the_typeface_of_the_interface() -> None:
    # A report is opened far from the installation, so Inter travels inside it.
    text = html_of(QBR, "A")
    carried = re.search(r"url\(data:font/woff2;base64,([A-Za-z0-9+/=]+)\)", text)
    assert carried is not None
    font = ROOT / "app/static/vendor/inter/inter-latin-opsz-normal.woff2"
    assert base64.b64decode(carried.group(1)) == font.read_bytes()
    assert text.index("@font-face") < text.index(
        'font-family: "Inter Variable", system-ui'
    )
    # The preview shows the report under a policy of its own: that font, its inline
    # style, a picture carried inside the file (the logo of the business) and
    # nothing else (no script, no address).
    policy = dict(part.split(" ", 1) for part in PREVIEW_POLICY.split("; "))
    assert policy["default-src"] == "'none'" and policy["font-src"] == "data:"
    assert policy["img-src"] == "data:"
    assert set(policy) == {
        "default-src",
        "style-src",
        "font-src",
        "img-src",
        "base-uri",
        "form-action",
        "frame-ancestors",
    }
    # A golden file names the typeface instead of holding it.
    golden = make_report_golden.golden_path(QBR, "A").read_bytes()
    assert make_report_golden.FONT_MARK in golden and len(golden) < 80_000


@pytest.mark.parametrize("kind", KINDS)
def test_no_revrook_logo_is_on_a_client_page(kind: str) -> None:
    text = html_of(kind, "A")
    head, body = text.split("</head>")
    assert "<img" not in text and "<picture" not in text
    # The one address of a report is the typeface it carries inside itself.
    assert text.count("url(") == 1 and "url(data:font/woff2;base64," in text
    assert "logo" not in body.lower() and "logo" not in head.split("<style>")[0]
    assert 'name="generator" content="revrook"' in head
    assert body.count(GENERATED_WITH) == len(SECTION.findall(body))
    assert body.lower().count("revrook") == len(SECTION.findall(body))


@pytest.mark.parametrize("kind", KINDS)
def test_the_msp_name_is_on_the_cover(kind: str) -> None:
    cover = SECTION.search(html_of(kind, "B"))
    assert cover is not None and report_clients.MSP in cover.group(0)


@pytest.mark.parametrize("kind", KINDS)
def test_a_report_loads_nothing_from_outside(kind: str) -> None:
    text = html_of(kind, "A")
    assert "<script" not in text and "<link" not in text and "src=" not in text
    links = re.findall(r'href="([^"]*)"', text)
    assert links and all(link.startswith("#rv-icon-") for link in links)


@pytest.mark.parametrize("name", NAMES)
def test_a_status_is_always_an_icon_and_its_words(name: str) -> None:
    text = html_of(QBR, name)
    spans = re.findall(r'<span class="status status-([a-z-]+)">(.*?)</span>', text)
    assert spans
    for key, inner in spans:
        words = re.sub(r"<svg.*?</svg>", "", inner, flags=re.DOTALL)
        assert 'class="rv-icon"' in inner, key
        assert words.strip() and "<" not in words, key


@pytest.mark.parametrize("name", NAMES)
def test_every_chart_is_followed_by_a_table_of_its_numbers(name: str) -> None:
    text = html_of(QBR, name)
    chart = text.index('<svg class="chart"')
    after = text[chart:]
    assert "<title" in after and "<desc" in after
    # The caption names the frame the table scrolls in (THE-1189 acceptance D3).
    numbers = '<caption id="coverage-caption">Data for the chart'
    assert numbers in after[after.index("</svg>") :]


# --- the look of the document ---------------------------------------------------------


def section_of(text: str, page_id: str) -> str | None:
    found = [m.group(0) for m in SECTION.finditer(text) if m.group(1) == page_id]
    return found[0] if found else None


def test_the_cover_of_the_review_carries_the_score_dial_and_the_pack_none() -> None:
    cover = section_of(html_of(QBR, "B"), "cover")
    assert cover is not None
    assert '<svg class="dial" role="img"' in cover
    assert "<title" in cover and "<desc" in cover
    assert f'text-anchor="middle">{EXPECTED_SCORES["B"]}</text>' in cover
    # The client and the period stand on the head of the cover, under the report.
    assert cover.index("<h1") < cover.index('class="cover-client"')
    pack = section_of(html_of(INSURANCE, "B"), "cover")
    assert pack is not None and 'class="dial"' not in pack


def test_the_dial_and_the_status_bar_are_drawn_from_whole_numbers() -> None:
    assert dial_dash(Fraction(0)) == 0 and dial_dash(Fraction(-3)) == 0
    assert dial_dash(Fraction(249, 10)) == 249
    assert dial_dash(Fraction(100)) == dial_dash(Fraction(140)) == DIAL_LENGTH
    assert segment_widths([0, 0, 0, 0]) == [0, 0, 0, 0]
    for counts in ([11, 4, 6, 30], [51, 0, 0, 0], [1, 1, 1, 48], [0, 0, 0, 1]):
        widths = segment_widths(counts)
        drawn = [width for width in widths if width]
        # A status with controls is always seen; the bar is exactly as wide as it is.
        assert [width > 0 for width in widths] == [count > 0 for count in counts]
        assert sum(widths) + MIX_GAP * (len(drawn) - 1) == WIDTH


@pytest.mark.parametrize("name", NAMES)
def test_the_status_bar_stands_on_the_table_of_its_numbers(name: str) -> None:
    text = html_of(QBR, name)
    after = text[text.index('<svg class="mix"') :]
    assert "<title" in after and "<desc" in after
    rest = after[after.index("</svg>") + len("</svg>") :]
    assert rest.lstrip().startswith(
        '<div class="table-scroll" role="region" tabindex="0" '
        'aria-labelledby="summary-status-caption">'
    )


def test_what_could_not_be_checked_names_the_evidence_it_waits_for() -> None:
    view = view_of("B")
    waiting = [row for row in view.rows if row.label == NOT_CHECKED]
    section = section_of(html_of(QBR, "B"), "unchecked")
    assert waiting and section is not None
    assert (
        f"{len(waiting)} of the {len(view.rows)} controls could not be checked"
        in section
    )
    for row in waiting:
        assert row.control_id in section, row.control_id
    # With every control checked there is nothing to say, and no empty section.
    checked = replace(
        view, rows=tuple(row for row in view.rows if row.label != NOT_CHECKED)
    )
    assert 'id="unchecked"' not in render_report(QBR, checked).decode("utf-8")


def test_a_client_never_reads_an_empty_roadmap() -> None:
    assert section_of(html_of(QBR, "A"), "roadmap") is not None
    bare = replace(report_clients.context_for("A"), findings={}, next_quarter_plan=())
    text = html_of(QBR, "A", bare)
    assert section_of(text, "roadmap") is None
    assert "has been entered yet" not in text
    # One of the two alone is printed without the empty heading of the other.
    plan = replace(bare, next_quarter_plan=("Review the firewall rules.",))
    section = section_of(html_of(QBR, "A", plan), "roadmap")
    assert section is not None
    assert "Plan for next quarter" in section and "<h3>Roadmap</h3>" not in section


@pytest.mark.parametrize("name", NAMES)
def test_a_domain_is_marked_where_it_is_named(name: str) -> None:
    text = html_of(QBR, name)
    symbols = set(re.findall(r'<symbol id="(rv-icon-dom-[a-z]+)"', text))
    used = set(re.findall(r'<use href="#(rv-icon-dom-[a-z]+)"/>', text))
    assert len(symbols) == 8 and used == symbols


def test_a_finding_says_what_the_check_found_when_the_snapshot_keeps_it() -> None:
    seen = "28 of 35 member users with MFA"
    context = replace(report_clients.context_for("B"), observed={"PC-ACC-01": seen})
    section = section_of(html_of(QBR, "B", context), "findings")
    assert section is not None
    assert f"<dt>What was checked</dt><dd>{seen}</dd>" in section
    # A snapshot made before the sentences were kept prints none.
    plain = section_of(html_of(QBR, "B"), "findings")
    assert plain is not None and "What was checked" not in plain


def test_every_control_has_a_usual_next_step_of_one_sentence() -> None:
    assert set(NEXT_STEPS) == {control.id for control in LIBRARY.controls}
    for control_id, step in NEXT_STEPS.items():
        assert step == step.strip() and step.endswith("."), control_id
        assert 30 <= len(step) <= 180, control_id


def test_a_finding_without_a_recommendation_prints_the_usual_next_step() -> None:
    view = view_of("B")
    written = [item for item in view.top_findings if item.finding.recommend]
    bare = [item for item in view.top_findings if not item.finding.recommend]
    assert written and bare
    section = section_of(render_report(QBR, view).decode("utf-8"), "findings")
    assert section is not None
    for item in bare:
        step = str(escape(NEXT_STEPS[item.row.control_id]))
        assert f"<dt>Usual next step</dt><dd>{step}</dd>" in section
    # What the technician recommends takes its place.
    for item in written:
        assert str(escape(NEXT_STEPS[item.row.control_id])) not in section
    assert section.count("<dt>Usual next step</dt>") == len(bare)
    # A control that passes on old evidence asks for fresh evidence, not a fix.
    first = bare[0]
    old = replace(first, row=replace(first.row, status="pass"))
    ranked = tuple(old if item is first else item for item in view.ranked)
    text = render_report(QBR, replace(view, ranked=ranked)).decode("utf-8")
    stale = section_of(text, "findings")
    assert stale is not None
    assert f"<dt>Usual next step</dt><dd>{REFRESH_EVIDENCE}</dd>" in stale
    assert str(escape(NEXT_STEPS[first.row.control_id])) not in stale


def test_the_evidence_is_named_as_a_client_reads_it() -> None:
    body = html_of(QBR, "B").split("</head>")[1]
    assert "Microsoft 365 export (Entra, Intune, Secure Score)" in body
    for shorthand in LIBRARY.source_codes.values():
        assert shorthand not in body, shorthand


@pytest.mark.parametrize("kind", KINDS)
def test_the_logo_of_the_business_stands_on_the_cover_inside_the_file(
    kind: str,
) -> None:
    data = base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(32)).decode("ascii")
    context = replace(report_clients.context_for("A"), logo=("image/png", data))
    text = html_of(kind, "A", context)
    cover = section_of(text, "cover")
    assert cover is not None
    mark = f'<img class="cover-mark" src="data:image/png;base64,{data}" alt="">'
    assert mark in cover and cover.index(mark) < cover.index(report_clients.MSP)
    # Still one file that loads nothing: the picture and the typeface are inside it.
    assert text.count("<img") == 1 and text.count("src=") == 1
    assert text.count("url(") == 1


# --- built from a stored snapshot only ------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_a_report_regenerated_from_an_old_snapshot_is_byte_identical(
    kind: str,
) -> None:
    old = report_clients.snapshot_bytes(LIBRARY, "B")
    first = render_report(
        kind, build_view(old, LIBRARY, report_clients.context_for("B"))
    )
    again = render_report(
        kind, build_view(regenerate(old), LIBRARY, report_clients.context_for("B"))
    )
    stored_and_read = render_snapshot(parse_snapshot(old))
    third = render_report(
        kind,
        build_view(stored_and_read, LIBRARY, report_clients.context_for("B")),
    )
    assert first == again == third


def test_an_edited_snapshot_is_refused() -> None:
    data = report_clients.snapshot_bytes(LIBRARY, "A")
    edited = data.replace(b'"status":"pass"', b'"status":"fail"', 1)
    assert edited != data
    with pytest.raises(ReportError):
        build_view(edited, LIBRARY, report_clients.context_for("A"))


def test_a_snapshot_of_another_ruleset_is_refused() -> None:
    data = report_clients.snapshot_bytes(LIBRARY, "A")
    other = replace(LIBRARY, version="9.9.9")
    with pytest.raises(ReportError, match="was made with"):
        build_view(data, other, report_clients.context_for("A"))


def test_other_details_make_another_report_with_the_same_numbers() -> None:
    context = replace(report_clients.context_for("A"), prepared_by="Another Person")
    changed = html_of(QBR, "A", context)
    assert "Another Person" in changed
    assert "<dd>89.5 out of 100</dd>" in changed


# --- escaping -------------------------------------------------------------------------


def hostile_context(name: str) -> ReportContext:
    base = report_clients.context_for(name)
    return replace(
        base,
        msp_name=f"MSP {HOSTILE}",
        client_name=f"Client {HOSTILE}",
        prepared_by=f"Tech {HOSTILE}",
        data_sources=(f"Source {HOSTILE}",),
        findings={
            "PC-ACC-01": Finding(
                did=f"did {HOSTILE}",
                recommend=f"recommend {HOSTILE}",
                need=f"need {HOSTILE}",
                by_when=f"when {HOSTILE}",
            )
        },
        next_quarter_plan=(f"plan {HOSTILE}",),
        exceptions=(
            ExceptionEntry(
                "PC-DEV-05",
                f"owner {HOSTILE}",
                f"reason {HOSTILE}",
                f"compensating {HOSTILE}",
                base.generated_on + timedelta(days=60),
            ),
        ),
        na_reviews={
            "PC-NET-04": NaReview(
                f"no wireless {HOSTILE}", f"reviewer {HOSTILE}", f"second {HOSTILE}"
            )
        },
        topic_owners={"backup": f"owner {HOSTILE}"},
    )


@pytest.mark.parametrize("kind", KINDS)
def test_hostile_names_and_exception_text_are_printed_as_text(kind: str) -> None:
    text = html_of(kind, "A", hostile_context("A"))
    for tag in ("<script", "<img src=x", "onerror=y>", '"x")</script>'):
        assert tag not in text, tag
    escaped = str(escape(HOSTILE))
    assert escaped in text
    assert text.count("&lt;script&gt;") >= 4
    title = re.search(r"<title>(.*?)</title>", text)
    assert title is not None and "<script" not in title.group(1)


def test_a_hostile_not_applicable_reason_is_escaped_in_the_report() -> None:
    text = html_of(QBR, "A", hostile_context("A"))
    assert str(escape(f"no wireless {HOSTILE}")) in text
    assert "no wireless <script" not in text


def test_every_text_a_person_can_enter_is_escaped_in_both_reports() -> None:
    for kind in KINDS:
        text = html_of(kind, "C", hostile_context("C"))
        assert not re.search(r"<script|<img|<iframe|javascript:", text)


# --- the completeness check -----------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_the_worked_clients_are_complete(name: str) -> None:
    assert completeness_problems(view_of(name)) == ()


def with_control(name: str, control_id: str, **changes: Any) -> ReportView:
    snapshot = parse_snapshot(report_clients.snapshot_bytes(LIBRARY, name))
    controls = tuple(
        replace(item, **changes) if item.control_id == control_id else item
        for item in snapshot.controls
    )
    data = render_snapshot(replace(snapshot, controls=controls))
    return build_view(data, LIBRARY, report_clients.context_for(name))


def test_a_result_with_no_dated_evidence_blocks_the_export_and_is_not_protected() -> (
    None
):
    view = with_control("A", "PC-ACC-01", evidence_at=None)
    row = next(item for item in view.rows if item.control_id == "PC-ACC-01")
    assert row.label == NOT_CHECKED
    with pytest.raises(ExportBlockedError) as caught:
        ensure_complete(view)
    assert caught.value.problems == ("PC-ACC-01: a result with no dated evidence",)


def test_evidence_dated_after_the_pack_date_blocks_the_export() -> None:
    snapshot = parse_snapshot(report_clients.snapshot_bytes(LIBRARY, "A"))
    later = snapshot.as_of + timedelta(days=1)
    view = with_control("A", "PC-ACC-02", evidence_at=later)
    problems = completeness_problems(view)
    assert problems == ("PC-ACC-02: evidence dated after the pack date",)
    row = next(item for item in view.rows if item.control_id == "PC-ACC-02")
    assert row.label == NOT_CHECKED


def test_not_applicable_with_no_reason_blocks_the_export() -> None:
    view = with_control("B", "PC-NET-01", status="na", evidence_at=None)
    assert completeness_problems(view) == ("PC-NET-01: not applicable with no reason",)


def test_a_gate_control_marked_not_applicable_needs_a_second_reviewer() -> None:
    base = report_clients.context_for("B")
    context = replace(
        base,
        na_reviews={"PC-ACC-01": NaReview("No sign-in is used.", "Sam Technician")},
    )
    snapshot = parse_snapshot(report_clients.snapshot_bytes(LIBRARY, "B"))
    controls = tuple(
        replace(item, status="na", evidence_at=None)
        if item.control_id == "PC-ACC-01"
        else item
        for item in snapshot.controls
    )
    data = render_snapshot(replace(snapshot, controls=controls))
    problems = completeness_problems(build_view(data, LIBRARY, context))
    assert problems == (
        "PC-ACC-01: not applicable, a gate control needs a second reviewer",
    )


def test_report_details_that_are_missing_or_too_long_block_the_export() -> None:
    base = report_clients.context_for("A")
    blank = replace(base, msp_name=" ", prepared_by="")
    problems = completeness_problems(view_of("A", blank))
    assert (
        "the name of your business is not set" in problems
        and "the preparer is empty" in problems
    )
    long_name = replace(base, client_name="x" * (MAX_NAME + 1))
    assert any(
        "client name is longer" in item
        for item in completeness_problems(view_of("A", long_name))
    )
    backwards = replace(base, period_end=base.period_start - timedelta(days=1))
    assert "the period ends before it starts" in completeness_problems(
        view_of("A", backwards)
    )


def test_a_finding_for_a_control_that_does_not_exist_blocks_the_export() -> None:
    base = report_clients.context_for("A")
    context = replace(base, findings={**base.findings, "PC-NOPE-99": Finding(did="x")})
    problems = completeness_problems(view_of("A", context))
    assert problems == ("a finding names 'PC-NOPE-99', not a control",)


# --- a Met status without dated evidence cannot be produced ---------------------------


def random_controls(rng: random.Random, as_of: datetime) -> tuple[ControlInput, ...]:
    """A random state of all 51 controls, with and without dated evidence."""
    found: list[ControlInput] = []
    for control in LIBRARY.controls:
        status = rng.choice(["pass", "partial", "fail", "unknown", "na"])
        quality = rng.choice([Fraction(1), Fraction(9, 10), Fraction(3, 5)])
        kind = rng.choice(["none", "past", "past", "now", "future", "stale"])
        past = timedelta(days=rng.randint(0, 20), hours=rng.randint(0, 23))
        at = {
            "none": None,
            "past": as_of - past,
            "now": as_of,
            "future": as_of + timedelta(hours=rng.randint(1, 72)),
            "stale": as_of - timedelta(days=rng.randint(60, 400)),
        }[kind]
        found.append(
            ControlInput(
                control_id=control.id,
                domain=control.domain,
                weight=control.weight,
                gate=control.gate,
                status=status,  # type: ignore[arg-type]
                quality=quality,
                evidence_at=at,
                max_age_days=control.max_age_days.automatic,
            )
        )
    return tuple(found)


def test_a_protected_status_always_has_dated_evidence_over_random_states() -> None:
    rng = random.Random(SEED)
    base = parse_snapshot(report_clients.snapshot_bytes(LIBRARY, "A"))
    context = report_clients.context_for("A")
    protected_seen = 0
    for _ in range(CASES):
        controls = random_controls(rng, base.as_of)
        data = render_snapshot(replace(base, controls=controls))
        view = build_view(data, LIBRARY, context)
        problems = completeness_problems(view)
        undated = [
            item.control_id
            for item in controls
            if item.status in ("pass", "partial", "fail")
            and (item.evidence_at is None or item.evidence_at > base.as_of)
        ]
        by_id = {item.control_id: item for item in controls}
        for row in view.rows:
            item = by_id[row.control_id]
            if row.label == PROTECTED:
                protected_seen += 1
                assert item.status == "pass", row.control_id
                assert item.evidence_at is not None, row.control_id
                assert item.evidence_at <= base.as_of, row.control_id
                assert row.evidence_at is not None, row.control_id
            if item.status == "na":
                assert row.label == NOT_APPLICABLE
            if row.control_id in undated:
                assert row.label == NOT_CHECKED, row.control_id
        flagged = {
            problem.split(":")[0]
            for problem in problems
            if "no dated evidence" in problem or "dated after" in problem
        }
        assert flagged == set(undated)
        if undated:
            with pytest.raises(ExportBlockedError):
                ensure_complete(view)
    assert protected_seen > CASES, "the cases must reach the Protected label"


# --- topics and order are fixed -------------------------------------------------------


def test_the_report_depends_on_the_view_alone() -> None:
    first = render_report(QBR, view_of("B"))
    second = render_report(QBR, view_of("B"))
    assert first == second
    assert render_report(INSURANCE, view_of("B")) == render_report(
        INSURANCE, view_of("B")
    )


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="not a kind of report"):
        render_report("deck", view_of("A"))
