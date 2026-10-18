"""What the rules share: reading facts, ages, thresholds and outcomes.

Everything here is pure. A time is read from the ISO text an importer stored; an
age is measured from the capture time of the evidence item the time came from,
never from a clock. A time later than the capture time cannot be an age: the
capture time or the clock of the tool is wrong, so the value is unreadable (None)
and a rule can never pass on it. A window is inclusive: a time exactly N days
before the capture time is within N days.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction

from app.checks.library import Control, Threshold
from app.checks.model import (
    ABSENT,
    EMPTY_POPULATION,
    UNRESOLVED,
    Evidence,
    Outcome,
    Row,
    SourceFacts,
    Status,
    Value,
)

MICROSECONDS_PER_HOUR = 3_600_000_000


@dataclass(frozen=True)
class Context:
    """One control and the evidence it is evaluated against."""

    control: Control
    evidence: Evidence

    def source(self, adapter: str) -> SourceFacts | None:
        return self.evidence.sources.get(adapter)


def parse_time(value: Value) -> datetime | None:
    """The time an importer stored as ISO text; a time without a zone is UTC."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def within(captured_at: datetime, value: Value, days: int) -> bool | None:
    """Whether a time is at most `days` days before the capture time.

    None when the time is missing, unreadable or later than the capture time.
    """
    stamp = parse_time(value)
    if stamp is None or stamp > captured_at:
        return None
    return captured_at - stamp <= timedelta(days=days)


def within_hours(captured_at: datetime, value: Value, hours: Fraction) -> bool | None:
    """Like `within`, for a window of exact hours (a schedule times a factor)."""
    stamp = parse_time(value)
    if stamp is None or stamp > captured_at:
        return None
    elapsed = Fraction((captured_at - stamp) // timedelta(microseconds=1))
    return elapsed <= hours * MICROSECONDS_PER_HOUR


def text_of(value: Value) -> str | None:
    """A non-empty text value, else None."""
    return value if isinstance(value, str) and value else None


def count_of(value: Value) -> int | None:
    """A whole-number value (a flag is not a number), else None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def flag_of(value: Value) -> bool | None:
    return value if isinstance(value, bool) else None


def oldest(stamps: Iterable[datetime | None]) -> datetime | None:
    """The oldest of the times given, ignoring the missing ones."""
    found = [stamp for stamp in stamps if stamp is not None]
    return min(found) if found else None


def active_rows(
    source: SourceFacts, kind: str, column: str, days: int
) -> tuple[Row, ...]:
    """The rows of a kind whose time column is within the window (the DV window)."""
    return tuple(
        row
        for row in source.rows(kind)
        if within(source.captured_at, row.get(column), days) is True
    )


# --- thresholds -------------------------------------------------------------


def _least(threshold: Threshold | None) -> Fraction | None:
    if threshold is None or threshold.at_least is None:
        return None
    return Fraction(threshold.at_least)


def _most(threshold: Threshold | None) -> int | None:
    return None if threshold is None else threshold.at_most


def share_status(control: Control, numerator: int, denominator: int) -> Status:
    """pass, partial or fail for a share, with the exact thresholds of the file."""
    share = Fraction(numerator, denominator)
    passing = _least(control.rule.pass_)
    partial = _least(control.rule.partial)
    if passing is not None and share >= passing:
        return "pass"
    if partial is not None and share >= partial:
        return "partial"
    return "fail"


def count_status(control: Control, count: int) -> Status:
    """pass, partial or fail for a count that should be small."""
    passing = _most(control.rule.pass_)
    partial = _most(control.rule.partial)
    if passing is not None and count <= passing:
        return "pass"
    if partial is not None and count <= partial:
        return "partial"
    return "fail"


# --- outcomes ---------------------------------------------------------------


def unknown(reason: str, detail: str, at: datetime | None = None) -> Outcome:
    return Outcome("unknown", reason, detail, evidence_at=at)


def absent(detail: str) -> Outcome:
    """The field is not in the evidence: never pass and never fail."""
    return unknown(ABSENT, detail)


def decided(
    status: Status,
    detail: str,
    at: datetime | None,
    numerator: int | None = None,
    denominator: int | None = None,
) -> Outcome:
    return Outcome(status, None, detail, numerator, denominator, at)


def share_outcome(
    control: Control,
    numerator: int,
    denominator: int,
    at: datetime | None,
    what: str,
    unresolved: int = 0,
) -> Outcome:
    detail = f"{numerator} of {denominator} {what}"
    if unresolved:
        detail += f"; {unresolved} could not be told from the export"
    status = share_status(control, numerator, denominator)
    return decided(status, detail, at, numerator, denominator)


def count_outcome(
    control: Control,
    found: int,
    unresolved: int,
    at: datetime | None,
    what: str,
    population: int | None = None,
) -> Outcome:
    """A count rule where few is good, with rows whose value cannot be told.

    The count is between `found` and `found + unresolved`. When the thresholds
    give the same status at both ends that is the result; otherwise the control
    is unknown, never the kinder status.
    """
    best = count_status(control, found)
    worst = count_status(control, found + unresolved)
    detail = f"{found} {what}"
    if unresolved:
        detail += f"; {unresolved} could not be told from the export"
    if best != worst:
        return Outcome("unknown", UNRESOLVED, detail, found, population, at)
    return decided(best, detail, at, found, population)


def share_of_known(
    control: Control,
    rows: Sequence[Row],
    test: Callable[[Row], bool | None],
    at: datetime | None,
    what: str,
) -> Outcome:
    """A share rule over a population: how many rows pass the test.

    A row whose test cannot be told (None) is left out of the share and counted in
    the detail. No rows is an empty population (unknown); rows that all cannot be
    told are an absent field (unknown).
    """
    if not rows:
        return unknown(EMPTY_POPULATION, f"There are no {what} to measure.", at)
    verdicts = [test(row) for row in rows]
    known = [verdict for verdict in verdicts if verdict is not None]
    if not known:
        return unknown(ABSENT, f"No {what} reports the values this control needs.", at)
    passing = sum(1 for verdict in known if verdict)
    return share_outcome(control, passing, len(known), at, what, len(rows) - len(known))


def worst_of(
    states: Sequence[Status | None],
    at: datetime | None,
    what: str,
    reason: str = UNRESOLVED,
) -> Outcome:
    """A control over several items: fail as soon as one fails, pass if all pass.

    An item that cannot be told (None) is never read kindly: with no failure the
    control is unknown. Items that all pass or partly pass give pass or partial.
    """
    total = len(states)
    passing = sum(1 for state in states if state == "pass")
    unresolved = sum(1 for state in states if state is None)
    detail = f"{passing} of {total} {what}"
    if unresolved:
        detail += f"; {unresolved} could not be told"
    if "fail" in states:
        return decided("fail", detail, at, passing, total)
    if unresolved:
        return unknown(reason, detail, at)
    status: Status = "pass" if passing == total else "partial"
    return decided(status, detail, at, passing, total)


def no_source(*adapters: str) -> Outcome:
    """Unknown because a source was never imported."""
    names = " and ".join(adapters)
    return absent(f"Nothing was imported from {names}.")
