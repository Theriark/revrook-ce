"""The completeness check: what blocks an export.

A report must not say more than its evidence shows. Before a file can be exported the
check looks for a claim that has nothing behind it: a result (Protected, Needs
attention or Not protected) with no dated evidence, evidence dated after the pack
date, a control marked not applicable without a reviewer's reason (and a second
reviewer for a gate control), or a snapshot that names no evidence at all. It also
refuses report details that are missing or too long. `ensure_complete` raises
`ExportBlockedError` with every problem named; nothing is left to the reader to find.

The labels of `app/reports/status.py` already turn a claim without dated evidence
into Not checked, so such a claim could never be printed as Met or Protected; this
check goes further and stops the export, because a snapshot that holds a result with
no date is not a pack to send to a client.
"""

from app.checks.engine import na_review_problem
from app.exceptions import exception_problems
from app.reports.topics import TOPIC_KEYS
from app.reports.view import ReportView

MAX_NAME = 200
MAX_SHORT = 100
MAX_TEXT = 2000
MAX_LIST = 50
CLAIMS = ("pass", "partial", "fail")


class ExportBlockedError(Exception):
    """A report cannot be exported yet. `problems` names every reason."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems[:5]))


def _shown(value: str) -> str:
    return repr(value if len(value) <= 40 else value[:40] + "...")


def _text(label: str, value: str, limit: int, required: bool = False) -> list[str]:
    """What is wrong with one text: empty (when it is needed) or too long."""
    if required and not value.strip():
        return [f"{label} is empty"]
    if len(value) > limit:
        return [f"{label} is longer than {limit} characters"]
    return []


def _details(view: ReportView) -> list[str]:
    context = view.context
    problems: list[str] = []
    problems += _text("the MSP name", context.msp_name, MAX_SHORT, True)
    problems += _text("the client name", context.client_name, MAX_NAME, True)
    problems += _text("the preparer", context.prepared_by, MAX_SHORT, True)
    if context.period_end < context.period_start:
        problems.append("the period ends before it starts")
    longest = max(len(context.data_sources), len(context.next_quarter_plan))
    if longest > MAX_LIST:
        problems.append("there are too many data sources or plan lines")
    for source in context.data_sources[:MAX_LIST]:
        problems += _text("a data source", source, MAX_SHORT, True)
    for line in context.next_quarter_plan[:MAX_LIST]:
        problems += _text("a line of the plan", line, MAX_TEXT, True)
    for owner in context.topic_owners.values():
        problems += _text("a topic owner", owner, MAX_SHORT, True)
    known = {row.control_id for row in view.rows}
    for control_id, finding in context.findings.items():
        if control_id not in known:
            problems.append(f"a finding names {_shown(control_id)}, not a control")
            continue
        label = f"{control_id}: a finding"
        for part in (finding.did, finding.recommend, finding.need, finding.by_when):
            problems += _text(label, part, MAX_TEXT)
    for entry in context.exceptions:
        if entry.control_id not in known:
            problems.append(f"an exception names {_shown(entry.control_id)}")
        problems += [f"{entry.control_id}: {p}" for p in exception_problems(entry)]
    if context.asked_topics is not None:
        for key in sorted(context.asked_topics - set(TOPIC_KEYS)):
            problems.append(f"{_shown(key)} is not a topic of the pack")
    for key in sorted(set(context.topic_owners) - set(TOPIC_KEYS)):
        problems.append(f"an owner is given for {_shown(key)}, not a topic")
    return problems


def _claims(view: ReportView) -> list[str]:
    snapshot = view.snapshot
    problems: list[str] = []
    claimed = False
    for item in snapshot.controls:
        name = item.control_id
        if item.status in CLAIMS:
            claimed = True
            if item.evidence_at is None:
                problems.append(f"{name}: a result with no dated evidence")
            elif item.evidence_at > snapshot.as_of:
                problems.append(f"{name}: evidence dated after the pack date")
        elif item.status == "na":
            review = view.context.na_reviews.get(name)
            if review is None:
                problems.append(f"{name}: not applicable with no reason")
                continue
            problem = na_review_problem(item.gate, review)
            if problem is not None:
                problems.append(f"{name}: not applicable, {problem}")
            for part in (review.reason, review.reviewer):
                problems += _text(f"{name}: the note", part, MAX_TEXT)
    if claimed and not snapshot.evidence:
        problems.append("the snapshot names no evidence behind its results")
    return problems


def completeness_problems(view: ReportView) -> tuple[str, ...]:
    """Every reason the report cannot be exported yet (empty: it can)."""
    return tuple([*_details(view), *_claims(view)])


def ensure_complete(view: ReportView) -> None:
    """Raise ExportBlockedError unless the report may be exported."""
    problems = completeness_problems(view)
    if problems:
        raise ExportBlockedError(problems)
