"""The view model of a report: a stored snapshot plus the details of one report.

`build_view` reads a snapshot (its digest is checked, so an edited pack is refused),
scores its stored inputs (the same exact arithmetic that made it) and joins the
wording of the control library of the same ruleset version. It reads no clock and
no database: the same snapshot, library and details give the same view, so the same
HTML. The details (`ReportContext`) are what a technician writes for one report: the
MSP and client names, the period, what was done and recommended, the exceptions.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction

from app.checks.library import Library
from app.checks.model import NaReview, Status
from app.exceptions import ExceptionEntry, is_overdue
from app.reports.status import (
    COUNTED_LABELS,
    NEEDS_ATTENTION,
    NOT_APPLICABLE,
    NOT_CHECKED,
    NOT_PROTECTED,
    PROTECTED,
    StatusLabel,
    assurance_of,
    has_dated_evidence,
    label_for,
)
from app.reports.topics import LABEL_BY_TOPIC_STATUS, TOPICS, Topic, topic_status
from app.scoring.display import format_fixed, headline, percent
from app.scoring.model import ControlInput, ScoreResult
from app.scoring.snapshot import (
    SnapshotError,
    SnapshotInput,
    parse_snapshot,
    score_snapshot,
    trend,
)

EXPIRING_DAYS = 30
TOP_FINDINGS = 5
LATEST = datetime.max.replace(tzinfo=UTC)
NOT_ENTERED = "Not yet entered"

EVIDENCE_NONE = "No dated evidence"
EVIDENCE_CURRENT = "Current"
EVIDENCE_EXPIRING = "Expires within 30 days"
EVIDENCE_EXPIRED = "Expired"


class ReportError(ValueError):
    """The snapshot cannot be turned into a report (edited, or another ruleset)."""


@dataclass(frozen=True)
class Finding:
    """What the technician wrote about one control (all four are optional)."""

    did: str = ""
    recommend: str = ""
    need: str = ""
    by_when: str = ""


@dataclass(frozen=True)
class ReportContext:
    """The details of one report. Every text is printed escaped."""

    msp_name: str
    client_name: str
    period_start: date
    period_end: date
    prepared_by: str
    generated_on: date
    data_sources: tuple[str, ...] = ()
    findings: Mapping[str, Finding] = field(default_factory=dict)
    next_quarter_plan: tuple[str, ...] = ()
    exceptions: tuple[ExceptionEntry, ...] = ()
    na_reviews: Mapping[str, NaReview] = field(default_factory=dict)
    topic_owners: Mapping[str, str] = field(default_factory=dict)
    asked_topics: frozenset[str] | None = None


@dataclass(frozen=True)
class ControlRow:
    """One control as a report shows it."""

    control_id: str
    title: str
    domain_code: str
    domain_name: str
    weight: int
    gate: bool
    status: Status
    label: StatusLabel
    evidence_at: datetime | None
    expires_at: datetime | None
    evidence_state: str
    assurance: str
    na_note: str | None
    sources: tuple[str, ...]

    @property
    def counted(self) -> bool:
        return self.label != NOT_APPLICABLE


@dataclass(frozen=True)
class DomainRow:
    code: str
    name: str
    weight: int
    score: Fraction | None
    counts: tuple[tuple[StatusLabel, int], ...]

    @property
    def score_text(self) -> str:
        return "Not applicable" if self.score is None else format_fixed(self.score)


@dataclass(frozen=True)
class TopicRow:
    topic: Topic
    status: str
    checked: int
    counted: int
    oldest_evidence: datetime | None
    owner: str
    asked: bool
    rows: tuple[ControlRow, ...]

    @property
    def label(self) -> StatusLabel:
        """The status of the topic as an icon and words (Met, Partly, ...)."""
        return LABEL_BY_TOPIC_STATUS[self.status]

    @property
    def coverage_text(self) -> str:
        if not self.counted:
            return "0"
        return percent(Fraction(self.checked, self.counted))


@dataclass(frozen=True)
class FindingRow:
    rank: int
    row: ControlRow
    finding: Finding


@dataclass(frozen=True)
class ExceptionRow:
    """An open exception beside the control it belongs to."""

    row: ControlRow | None
    control_id: str
    owner: str
    reason: str
    compensating_control: str | None
    review_date: date
    overdue: bool


@dataclass(frozen=True)
class ReportView:
    context: ReportContext
    snapshot: SnapshotInput
    snapshot_sha256: str
    result: ScoreResult
    rows: tuple[ControlRow, ...]
    domains: tuple[DomainRow, ...]
    topics: tuple[TopicRow, ...]
    ranked: tuple[FindingRow, ...]
    actions: tuple[FindingRow, ...]
    register: tuple[ExceptionRow, ...]
    summary_lines: tuple[str, ...]
    counts: tuple[tuple[StatusLabel, int], ...]

    @property
    def top_findings(self) -> tuple[FindingRow, ...]:
        return self.ranked[:TOP_FINDINGS]

    @property
    def expiring(self) -> tuple[ControlRow, ...]:
        """Evidence that has expired or expires within 30 days, soonest first."""
        due = [
            row
            for row in self.rows
            if row.evidence_state in (EVIDENCE_EXPIRED, EVIDENCE_EXPIRING)
        ]
        return tuple(
            sorted(due, key=lambda row: (row.expires_at or LATEST, row.control_id))
        )


def iso_date(value: datetime) -> str:
    """The UTC date of a moment as YYYY-MM-DD."""
    return value.astimezone(UTC).date().isoformat()


def _evidence_state(
    item: ControlInput, as_of: datetime, dated: bool
) -> tuple[datetime | None, str]:
    """When the evidence expires (None: never, or no evidence) and where it stands."""
    if not dated:
        return None, EVIDENCE_NONE
    if item.evidence_at is None or item.max_age_days is None:
        return None, EVIDENCE_CURRENT
    expires = item.evidence_at + timedelta(days=item.max_age_days)
    if expires < as_of:
        return expires, EVIDENCE_EXPIRED
    if expires - as_of <= timedelta(days=EXPIRING_DAYS):
        return expires, EVIDENCE_EXPIRING
    return expires, EVIDENCE_CURRENT


def _rows(
    snapshot: SnapshotInput,
    result: ScoreResult,
    library: Library,
    context: ReportContext,
) -> tuple[ControlRow, ...]:
    names = {domain.code: domain.name for domain in library.domains}
    scored = {item.control_id: item for item in result.controls}
    titles = {control.id: control.title for control in library.controls}
    sources = {
        control.id: tuple(
            library.source_codes.get(code, code) for code in control.sources
        )
        for control in library.controls
    }
    rows: list[ControlRow] = []
    for item in snapshot.controls:
        if item.control_id not in titles:
            raise ReportError(f"{item.control_id} is not a control of this ruleset")
        label = label_for(item, scored[item.control_id], snapshot.as_of)
        dated = has_dated_evidence(item, snapshot.as_of)
        expires, state = _evidence_state(item, snapshot.as_of, dated)
        review = context.na_reviews.get(item.control_id)
        note = None
        if label == NOT_APPLICABLE and review is not None:
            note = f"{review.reason} ({review.reviewer})"
        rows.append(
            ControlRow(
                control_id=item.control_id,
                title=titles[item.control_id],
                domain_code=item.domain,
                domain_name=names.get(item.domain, item.domain),
                weight=item.weight,
                gate=item.gate,
                status=item.status,
                label=label,
                evidence_at=item.evidence_at if dated else None,
                expires_at=expires,
                evidence_state=state,
                assurance=assurance_of(item) if dated else "No evidence",
                na_note=note,
                sources=sources[item.control_id],
            )
        )
    return tuple(rows)


def _counts(rows: tuple[ControlRow, ...]) -> tuple[tuple[StatusLabel, int], ...]:
    return tuple(
        (label, sum(1 for row in rows if row.label == label))
        for label in COUNTED_LABELS
    )


def _domains(
    result: ScoreResult, library: Library, rows: tuple[ControlRow, ...]
) -> tuple[DomainRow, ...]:
    names = {domain.code: domain.name for domain in library.domains}
    return tuple(
        DomainRow(
            code=item.code,
            name=names.get(item.code, item.code),
            weight=item.weight,
            score=item.score,
            counts=_counts(tuple(row for row in rows if row.domain_code == item.code)),
        )
        for item in result.domains
    )


def _topic_rows(
    rows: tuple[ControlRow, ...], context: ReportContext
) -> tuple[TopicRow, ...]:
    by_id = {row.control_id: row for row in rows}
    found: list[TopicRow] = []
    for topic in TOPICS:
        members = tuple(by_id[cid] for cid in topic.control_ids if cid in by_id)
        counted = [row for row in members if row.counted]
        checked = [row for row in counted if row.label != NOT_CHECKED]
        dated = [row.evidence_at for row in checked if row.evidence_at is not None]
        asked = context.asked_topics is None or topic.key in context.asked_topics
        found.append(
            TopicRow(
                topic=topic,
                status=topic_status([row.label for row in members]),
                checked=len(checked),
                counted=len(counted),
                oldest_evidence=min(dated) if dated else None,
                owner=context.topic_owners.get(topic.key, "Not assigned"),
                asked=asked,
                rows=members,
            )
        )
    return tuple(found)


def _urgency(row: ControlRow) -> tuple[int, int, int, str]:
    """Smaller is more urgent: gates first, then what is not protected, then weight."""
    order = {NOT_PROTECTED: 0, NEEDS_ATTENTION: 1, NOT_CHECKED: 2}
    return (0 if row.gate else 1, order[row.label], -row.weight, row.control_id)


def _ranked(
    rows: tuple[ControlRow, ...], context: ReportContext, *, with_unchecked: bool
) -> tuple[FindingRow, ...]:
    wanted = {NOT_PROTECTED, NEEDS_ATTENTION}
    if with_unchecked:
        wanted.add(NOT_CHECKED)
    chosen = sorted((row for row in rows if row.label in wanted), key=_urgency)
    return tuple(
        FindingRow(rank, row, context.findings.get(row.control_id, Finding()))
        for rank, row in enumerate(chosen, start=1)
    )


def _register(
    rows: tuple[ControlRow, ...], context: ReportContext, as_of: datetime
) -> tuple[ExceptionRow, ...]:
    by_id = {row.control_id: row for row in rows}
    entries = sorted(
        context.exceptions,
        key=lambda entry: (entry.review_date, entry.control_id, entry.owner),
    )
    return tuple(
        ExceptionRow(
            row=by_id.get(entry.control_id),
            control_id=entry.control_id,
            owner=entry.owner,
            reason=entry.reason,
            compensating_control=entry.compensating_control,
            review_date=entry.review_date,
            overdue=is_overdue(entry, as_of),
        )
        for entry in entries
    )


def _plural(count: int, one: str, many: str) -> str:
    """The count with the word that fits it: 1 is, 2 are."""
    return f"{count} {one if count == 1 else many}"


def _movement(what: str, value: Fraction, places: int) -> str:
    """How a number moved, in words: rose by 1 point, fell by 2.5 points."""
    text = format_fixed(abs(value), places)
    if text.strip("0.") == "":
        return f"{what} did not change"
    unit = "point" if text == "1" else "points"
    direction = "rose" if value > 0 else "fell"
    return f"{what} {direction} by {text} {unit}"


def _summary_lines(
    result: ScoreResult,
    snapshot: SnapshotInput,
    counts: tuple[tuple[StatusLabel, int], ...],
    previous: SnapshotInput | None,
) -> tuple[str, ...]:
    by_label = dict(counts)
    total = sum(by_label.values())
    second = "There is no earlier report to compare with."
    if previous is not None:
        change = trend(previous, snapshot)
        since = iso_date(previous.as_of)
        if change is None:
            second = (
                f"The report of {since} used another version of the rules, "
                "so the two scores are not compared."
            )
        else:
            score = _movement("the score", change.score_change, 1)
            coverage = _movement(
                "the evidence coverage", change.coverage_change * 100, 0
            )
            second = f"Since the report of {since} {score} and {coverage}."
    third = (
        f"Of {_plural(total, 'control', 'controls')}, "
        f"{_plural(by_label[PROTECTED], 'is', 'are')} Protected, "
        f"{_plural(by_label[NEEDS_ATTENTION], 'needs', 'need')} attention, "
        f"{_plural(by_label[NOT_PROTECTED], 'is', 'are')} not protected and "
        f"{_plural(by_label[NOT_CHECKED], 'was', 'were')} not checked."
    )
    return (headline(result) + ".", second, third)


def _digest_of(data: bytes) -> str:
    return str(json.loads(data.decode("utf-8"))["sha256"])


def build_view(
    data: bytes,
    library: Library,
    context: ReportContext,
    previous: bytes | None = None,
) -> ReportView:
    """The view of a report from the bytes of a stored snapshot.

    Raises ReportError when the snapshot cannot be read, was edited, or was made by
    another version of the rules than the library given (an old pack is read with
    the wording it was made with, never with the wording of today).
    """
    try:
        snapshot = parse_snapshot(data)
        earlier = None if previous is None else parse_snapshot(previous)
    except SnapshotError as error:
        raise ReportError(str(error)) from None
    made_with = (snapshot.ruleset_id, snapshot.ruleset_version)
    if made_with != (library.ruleset_id, library.version):
        raise ReportError(
            f"the snapshot was made with {made_with[0]} {made_with[1]}; "
            f"this install has {library.ruleset_id} {library.version}"
        )
    missing = {control.id for control in library.controls} - {
        item.control_id for item in snapshot.controls
    }
    if missing:
        raise ReportError(f"the snapshot has no result for {sorted(missing)[0]}")
    result = score_snapshot(snapshot)
    rows = _rows(snapshot, result, library, context)
    counts = _counts(rows)
    return ReportView(
        context=context,
        snapshot=snapshot,
        snapshot_sha256=_digest_of(data),
        result=result,
        rows=rows,
        domains=_domains(result, library, rows),
        topics=_topic_rows(rows, context),
        ranked=_ranked(rows, context, with_unchecked=False),
        actions=_ranked(rows, context, with_unchecked=True),
        register=_register(rows, context, snapshot.as_of),
        summary_lines=_summary_lines(result, snapshot, counts, earlier),
        counts=counts,
    )
