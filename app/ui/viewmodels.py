"""View models of the client pages: pure functions, no database and no request.

The checklist shows every control of the library as the report would show it today,
beside what changed since the last stored snapshot and why a row needs a look. The
evidence pages turn the stored items into one line per source, with the exports that
are out of date first, so the MSP knows which file to fetch next.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction

from app.checks.model import ControlResult
from app.evidence.assurance import Assurance
from app.evidence.expiry import Freshness
from app.evidence.service import EvidenceView
from app.reports.status import (
    NEEDS_ATTENTION,
    NOT_CHECKED,
    NOT_PROTECTED,
    StatusLabel,
    label_for,
)
from app.reports.topics import TOPICS
from app.reports.view import (
    EVIDENCE_EXPIRED,
    EVIDENCE_EXPIRING,
    ControlRow,
    ReportView,
)
from app.scoring.display import percent
from app.scoring.snapshot import (
    SnapshotError,
    SnapshotInput,
    parse_snapshot,
    score_snapshot,
)
from app.sources import refresh_instruction, source_name

NOT_ASSIGNED = "Not assigned"
NOT_MEASURED = "Not measured"
FLAGGED_LABELS = (NOT_PROTECTED, NEEDS_ATTENTION, NOT_CHECKED)
EXPIRED_FLAG = "Evidence expired"
EXPIRING_FLAG = "Evidence expires within 30 days"
EXCEPTION_FLAG = "Open exception"
LATEST = datetime.max.replace(tzinfo=UTC)
# Why a control is Not checked, in words for the person who reads the page.
REASON_TEXT = {
    "licence_or_scope": "The export has no such field, or the tool is not licensed.",
    "empty_population": "There was nothing of this kind to check.",
    "unresolved_values": "Some values in the export could not be read.",
    "no_artefact": "No artefact has been recorded for this control.",
    "lookup_failed": "A lookup failed, so nothing is claimed.",
    "no_permanent_assignment": "No permanent assignment was found to check.",
}

TOPIC_OF_CONTROL: dict[str, str] = {}
for _topic in TOPICS:
    for _control_id in _topic.control_ids:
        TOPIC_OF_CONTROL[_control_id] = _topic.key

# How an evidence source stands, shown like a status: an icon and the words.
CURRENT = StatusLabel("protected", "Current", "check")
STALE = StatusLabel("needs-attention", "Stale", "alert")
EXPIRED = StatusLabel("not-protected", "Expired", "cross")
MISSING = StatusLabel("not-checked", "Not imported", "question")
STATE_OF_FRESHNESS = {
    Freshness.CURRENT: CURRENT,
    Freshness.STALE: STALE,
    Freshness.EXPIRED: EXPIRED,
}


@dataclass(frozen=True)
class ChecklistRow:
    """One control on the checklist."""

    row: ControlRow
    coverage: str
    owner: str
    changed_from: StatusLabel | None
    reasons: tuple[str, ...]

    @property
    def changed(self) -> bool:
        """Whether the status differs from the last stored snapshot."""
        return self.changed_from is not None

    @property
    def flagged(self) -> bool:
        """Whether something about the row needs a look."""
        return bool(self.reasons)


def read_earlier(data: bytes | None) -> SnapshotInput | None:
    """The inputs of an earlier snapshot, or None when there is none or it is bad."""
    if data is None:
        return None
    try:
        return parse_snapshot(data)
    except SnapshotError:
        return None


def previous_labels(earlier: SnapshotInput | None) -> dict[str, StatusLabel]:
    """The status label every control had in an earlier snapshot."""
    if earlier is None:
        return {}
    scored = {item.control_id: item for item in score_snapshot(earlier).controls}
    labels: dict[str, StatusLabel] = {}
    for item in earlier.controls:
        labels[item.control_id] = label_for(
            item, scored[item.control_id], earlier.as_of
        )
    return labels


def reason_text(reason: str | None) -> str:
    """The words for the reason a control is unknown; empty when there is none."""
    if reason is None:
        return ""
    return REASON_TEXT.get(reason, reason)


def coverage_text(result: ControlResult | None) -> str:
    """How much of the population the control was checked on, for example 9 of 10."""
    if result is None or result.numerator is None or not result.denominator:
        return NOT_MEASURED
    share = percent(Fraction(result.numerator, result.denominator))
    return f"{result.numerator} of {result.denominator} ({share}%)"


def flags_of(row: ControlRow, excepted: bool) -> tuple[str, ...]:
    """Why a row needs a look: its status, old evidence or an open exception."""
    found: list[str] = []
    if row.label in FLAGGED_LABELS:
        found.append(row.label.text)
    if row.evidence_state == EVIDENCE_EXPIRED:
        found.append(EXPIRED_FLAG)
    elif row.evidence_state == EVIDENCE_EXPIRING:
        found.append(EXPIRING_FLAG)
    if excepted:
        found.append(EXCEPTION_FLAG)
    return tuple(found)


def checklist_rows(
    view: ReportView,
    results: Mapping[str, ControlResult],
    earlier: SnapshotInput | None,
    owners: Mapping[str, str],
    excepted: Collection[str],
) -> list[ChecklistRow]:
    """Every control of the view as a checklist row, in the order of the library."""
    before = previous_labels(earlier)
    rows: list[ChecklistRow] = []
    for row in view.rows:
        old = before.get(row.control_id)
        topic = TOPIC_OF_CONTROL.get(row.control_id, "")
        rows.append(
            ChecklistRow(
                row=row,
                coverage=coverage_text(results.get(row.control_id)),
                owner=owners.get(topic, NOT_ASSIGNED),
                changed_from=old if old is not None and old != row.label else None,
                reasons=flags_of(row, row.control_id in excepted),
            )
        )
    return rows


def only_flagged(rows: Sequence[ChecklistRow]) -> list[ChecklistRow]:
    """The rows whose status changed or that need a look; nothing else."""
    return [item for item in rows if item.changed or item.flagged]


@dataclass(frozen=True)
class SourceRow:
    """One evidence source of a client: its newest export and how old it is."""

    code: str
    name: str
    state: StatusLabel
    captured_at: datetime | None
    expires_at: datetime | None
    exports: int
    refresh: str | None


def source_rows(
    views: Sequence[EvidenceView], wanted: Collection[str]
) -> list[SourceRow]:
    """One row per source, by name: every source with an export, and every source
    that a control reads (`wanted`) even when nothing was imported yet.

    `views` come newest first (as `list_evidence` gives them), so the first export of
    a source is its newest.
    """
    newest: dict[str, EvidenceView] = {}
    counts: dict[str, int] = {}
    for view in views:
        if view.assurance is not Assurance.AUTOMATIC_EXPORT:
            continue
        counts[view.source_code] = counts.get(view.source_code, 0) + 1
        newest.setdefault(view.source_code, view)
    rows: list[SourceRow] = []
    for code, view in newest.items():
        state = STATE_OF_FRESHNESS[view.freshness]
        rows.append(
            SourceRow(
                code=code,
                name=source_name(code),
                state=state,
                captured_at=view.captured_at,
                expires_at=view.expires_at,
                exports=counts[code],
                refresh=None if state == CURRENT else refresh_instruction(code),
            )
        )
    for code in wanted:
        if code not in newest:
            rows.append(
                SourceRow(
                    code=code,
                    name=source_name(code),
                    state=MISSING,
                    captured_at=None,
                    expires_at=None,
                    exports=0,
                    refresh=refresh_instruction(code),
                )
            )
    return sorted(rows, key=lambda item: (item.name, item.code))


def refresh_list(rows: Sequence[SourceRow]) -> list[SourceRow]:
    """The sources to refresh: the oldest export first, then sources never imported."""

    def order(item: SourceRow) -> tuple[int, datetime, str]:
        if item.captured_at is None:
            return (1, LATEST, item.name)
        return (0, item.captured_at, item.name)

    return sorted((item for item in rows if item.refresh is not None), key=order)
