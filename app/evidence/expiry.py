"""Evidence age, freshness and expiry, in exact arithmetic.

The maximum age M of an item is the time after which it is stale. Freshness f
is 1 up to and including M, falls linearly and reaches 0 at 2 M:

    f = 1                     if age <= M
    f = 1 - (age - M) / M     if M < age < 2 M
    f = 0                     if age >= 2 M

Age is measured from the capture time of the export, never from a typed date.
Phase 5 reads the maximum age of each control; until then an item gets the
default of its assurance level (the most common maxima of the control library).
"""

import calendar
from datetime import datetime, timedelta
from enum import StrEnum
from fractions import Fraction

from app.evidence.assurance import Assurance

DEFAULT_MAX_AGE_DAYS: dict[Assurance, int] = {
    Assurance.AUTOMATIC_EXPORT: 35,
    Assurance.MANUAL_ARTEFACT: 365,
    Assurance.ATTESTATION: 365,
}
# Reminders are due when this many days (or fewer) are left before expiry.
REMINDER_THRESHOLD_DAYS = (30, 7, 0)
ONE_DAY = timedelta(days=1)


class Freshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    EXPIRED = "expired"


def default_max_age(assurance: Assurance) -> timedelta:
    return timedelta(days=DEFAULT_MAX_AGE_DAYS[assurance])


def stale_after(captured_at: datetime, max_age: timedelta) -> datetime:
    """The moment after which the item is stale (the item's expires_at)."""
    return captured_at + max_age


def expired_at(captured_at: datetime, max_age: timedelta) -> datetime:
    """The moment from which the item counts for nothing (twice the maximum age)."""
    return captured_at + 2 * max_age


def _microseconds(delta: timedelta) -> int:
    return delta // timedelta(microseconds=1)


def _require_positive(max_age: timedelta) -> None:
    if max_age <= timedelta(0):
        raise ValueError("the maximum age must be positive")


def freshness_factor(age: timedelta, max_age: timedelta) -> Fraction:
    """The freshness factor f for an age, as an exact fraction."""
    _require_positive(max_age)
    if age <= max_age:
        return Fraction(1)
    if age >= 2 * max_age:
        return Fraction(0)
    return 1 - Fraction(_microseconds(age - max_age), _microseconds(max_age))


def freshness_state(age: timedelta, max_age: timedelta) -> Freshness:
    """Current up to the maximum age, stale after it, expired at twice that age."""
    _require_positive(max_age)
    if age <= max_age:
        return Freshness.CURRENT
    if age >= 2 * max_age:
        return Freshness.EXPIRED
    return Freshness.STALE


def item_age(captured_at: datetime, as_of: datetime) -> timedelta:
    """The age at as_of. An item captured after as_of has age zero."""
    return max(as_of - captured_at, timedelta(0))


def state_of_item(
    captured_at: datetime, expires_at: datetime, as_of: datetime
) -> Freshness:
    """Freshness of a stored item: its maximum age is expires_at - captured_at."""
    return freshness_state(item_age(captured_at, as_of), expires_at - captured_at)


def raw_expires_at(stored_at: datetime, retention_days: int) -> datetime | None:
    """When a raw file must be deleted. None when it must not be kept at all."""
    if retention_days < 0:
        raise ValueError("the raw retention cannot be negative")
    if retention_days == 0:
        return None
    return stored_at + timedelta(days=retention_days)


def add_months(moment: datetime, months: int) -> datetime:
    """The same time of day some calendar months later, clamped to the month end."""
    index = moment.year * 12 + (moment.month - 1) + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def pack_expires_at(created_at: datetime, retention_months: int) -> datetime:
    """When a pack (snapshot or exported report) falls out of retention."""
    if retention_months < 1:
        raise ValueError("the pack retention must be at least one month")
    return add_months(created_at, retention_months)


def days_left(expires_at: datetime, now: datetime) -> int:
    """Whole days until expires_at (negative once it has passed), rounded down."""
    return (expires_at - now) // ONE_DAY


def reminder_thresholds_due(expires_at: datetime, now: datetime) -> tuple[int, ...]:
    """The reminder thresholds (in days) that have been reached by now."""
    left = days_left(expires_at, now)
    return tuple(days for days in REMINDER_THRESHOLD_DAYS if left <= days)
