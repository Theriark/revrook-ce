"""The HTML of the two reports, from a `ReportView` and the Jinja2 templates.

HTML is the shipping format (docs/pdf-spike.md): one file with its stylesheet inlined,
a print stylesheet for "Save as PDF" from a browser, inline SVG charts with a table
of the same numbers, and the disclaimer in the footer of every section (a page of the
HTML) and in full on the last. Every text that came from a person (names, reasons,
notes) goes through Jinja2 autoescape, so a hostile client name or exception text is
printed as text.

The output depends on the view alone: no clock, no random value, no dictionary
order that is not fixed. The same view is the same bytes.
"""

import functools
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.reports.charts import Bar, bar_chart
from app.reports.disclaimer import DISCLAIMER, GENERATED_WITH
from app.reports.status import NOT_APPLICABLE, NOT_PROTECTED
from app.reports.topics import TOPICS
from app.reports.view import (
    EVIDENCE_CURRENT,
    EVIDENCE_EXPIRED,
    EVIDENCE_EXPIRING,
    EVIDENCE_NONE,
    NOT_ENTERED,
    ControlRow,
    Finding,
    ReportView,
    iso_date,
)
from app.scoring.display import format_fixed, percent
from app.scoring.model import (
    GATE_EXPIRED,
    GATE_FAIL,
    GATE_PARTIAL,
    GATE_STALE,
    GATE_UNKNOWN,
)

HERE = Path(__file__).resolve().parent
QBR = "qbr"
INSURANCE = "insurance"
KINDS = (QBR, INSURANCE)
REPORT_NAMES = {
    QBR: "Quarterly security review",
    INSURANCE: "Cyber insurance evidence pack",
}
EXPIRING_SHOWN = 12
CAP_REASONS = {
    GATE_FAIL: "is not protected",
    GATE_UNKNOWN: "was not checked",
    GATE_EXPIRED: "has evidence that has expired",
    GATE_PARTIAL: "needs attention",
    GATE_STALE: "has evidence that is out of date",
}


@dataclass(frozen=True)
class RoadmapItem:
    priority: str
    row: ControlRow
    finding: Finding


def _day(value: datetime | date | None) -> str:
    if value is None:
        return "No date"
    if isinstance(value, datetime):
        return iso_date(value)
    return value.isoformat()


@functools.cache
def _environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(HERE / "templates"),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters["day"] = _day
    return environment


@functools.cache
def _stylesheet(name: str) -> Markup:
    text = (HERE / name).read_text(encoding="utf-8")
    # The comments explain the file to a developer; a report does not carry them.
    return Markup(re.sub(r"/\*.*?\*/\s*", "", text, flags=re.DOTALL).strip() + "\n")


def _numbers(view: ReportView) -> dict[str, str]:
    result = view.result
    titles = {row.control_id: row.title for row in view.rows}
    best = result.best_case
    best_text = (
        "Not shown: the evidence is too thin for a best case"
        if best is None
        else f"{format_fixed(best)} if every control that is not checked passed"
    )
    cap_text = ""
    if result.capped and result.cap is not None:
        cap = result.cap
        title = titles[cap.control_id].rstrip(".")
        cap_text = (
            f"The score of {format_fixed(result.raw)} is held at {cap.limit} because "
            f"{cap.control_id} {CAP_REASONS.get(cap.reason, 'limits it')} ({title})."
        )
    return {
        "score": format_fixed(result.score),
        "best_case": best_text,
        "coverage": percent(result.coverage),
        "band": result.band,
        "cap": cap_text,
    }


def _render(name: str, view: ReportView, report_name: str, **more: object) -> bytes:
    template = _environment().get_template(name)
    html = template.render(
        view=view,
        ctx=view.context,
        report_name=report_name,
        disclaimer=DISCLAIMER,
        generated_with=GENERATED_WITH,
        css=_stylesheet("report.css"),
        print_css=_stylesheet("print.css"),
        not_entered=NOT_ENTERED,
        **more,
    )
    return html.encode("utf-8")


def _domain_chart(view: ReportView) -> Markup:
    bars = [Bar(item.name, item.score, item.score_text) for item in view.domains]
    summary = "; ".join(f"{item.name} {item.score_text}" for item in view.domains)
    return bar_chart(
        "domain-chart",
        "Score by domain",
        f"Bars from 0 to 100, one for each domain. {summary}.",
        bars,
    )


def _roadmap(view: ReportView) -> list[RoadmapItem]:
    items: list[RoadmapItem] = []
    for item in view.ranked:
        if not item.finding.recommend.strip():
            continue
        urgent = item.row.gate or item.row.label == NOT_PROTECTED
        items.append(RoadmapItem("Now" if urgent else "Next", item.row, item.finding))
    return items


def render_qbr(view: ReportView) -> bytes:
    """The quarterly review as HTML (UTF-8)."""
    states = (EVIDENCE_CURRENT, EVIDENCE_EXPIRING, EVIDENCE_EXPIRED, EVIDENCE_NONE)
    counted = [row for row in view.rows if row.label != NOT_APPLICABLE]
    evidence_counts = [
        (state, sum(1 for row in counted if row.evidence_state == state))
        for state in states
    ]
    due = view.expiring
    appendix = [
        (domain, [row for row in view.rows if row.domain_code == domain.code])
        for domain in view.domains
    ]
    return _render(
        "qbr.html",
        view,
        REPORT_NAMES[QBR],
        n=_numbers(view),
        domain_chart=_domain_chart(view),
        roadmap=_roadmap(view),
        evidence_counts=evidence_counts,
        expiring=due[:EXPIRING_SHOWN],
        expiring_more=max(0, len(due) - EXPIRING_SHOWN),
        appendix=appendix,
    )


def render_insurance_pack(view: ReportView) -> bytes:
    """The insurance evidence pack as HTML (UTF-8)."""
    by_topic = {
        topic.key: [
            entry for entry in view.register if entry.control_id in topic.control_ids
        ]
        for topic in TOPICS
    }
    return _render(
        "insurance.html",
        view,
        REPORT_NAMES[INSURANCE],
        topics=view.topics,
        register_by_topic=by_topic,
    )


def render_report(kind: str, view: ReportView) -> bytes:
    """The HTML of a report of the given kind (`qbr` or `insurance`)."""
    if kind == QBR:
        return render_qbr(view)
    if kind == INSURANCE:
        return render_insurance_pack(view)
    raise ValueError(f"{kind!r} is not a kind of report; use one of {KINDS}")
