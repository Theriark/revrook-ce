"""The exceptions register: a control that is knowingly not met, and why.

An exception names the control, its owner, the reason, the compensating control
(what the client does instead, when there is one) and a review date. It is shown
beside the result of its control. It never changes the status, never raises the
score and never counts as evidence: a failed control with an exception is still a
failed control, and the exception tells the reader that someone decided to accept
it and when that decision must be looked at again.

An exception whose review date is before the pack date is overdue, and the flag
travels with it so a report can say so. An exception that is closed is not passed
to the engine. `exception_problems` says what an entry is missing before it is
saved.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

MAX_REASON_LENGTH = 2000


@dataclass(frozen=True)
class ExceptionEntry:
    """One open row of the exceptions register."""

    control_id: str
    owner: str
    reason: str
    compensating_control: str | None
    review_date: date


@dataclass(frozen=True)
class ExceptionNote:
    """An exception as it shows beside a result, with its overdue flag."""

    owner: str
    reason: str
    compensating_control: str | None
    review_date: date
    overdue: bool


def is_overdue(entry: ExceptionEntry, as_of: datetime) -> bool:
    """Whether the review date is before the pack date."""
    return entry.review_date < as_of.date()


def exception_problems(entry: ExceptionEntry) -> list[str]:
    """What is missing from an entry; an empty list means it may be saved."""
    problems: list[str] = []
    if not entry.owner.strip():
        problems.append("an exception needs an owner")
    if not entry.reason.strip():
        problems.append("an exception needs a reason")
    elif len(entry.reason) > MAX_REASON_LENGTH:
        problems.append(f"the reason is longer than {MAX_REASON_LENGTH} characters")
    compensating = entry.compensating_control
    if compensating is not None and not compensating.strip():
        problems.append("the compensating control is empty: give it or leave it out")
    return problems


def notes_for(
    entries: Iterable[ExceptionEntry], control_id: str, as_of: datetime
) -> tuple[ExceptionNote, ...]:
    """The exceptions of one control, oldest review date first."""
    chosen = sorted(
        (entry for entry in entries if entry.control_id == control_id),
        key=lambda entry: (entry.review_date, entry.owner),
    )
    return tuple(
        ExceptionNote(
            owner=entry.owner,
            reason=entry.reason,
            compensating_control=entry.compensating_control,
            review_date=entry.review_date,
            overdue=is_overdue(entry, as_of),
        )
        for entry in chosen
    )
