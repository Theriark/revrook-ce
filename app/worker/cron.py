"""Cron expressions for the schedule table: five fields, in UTC, standard library only.

`minute hour day-of-month month day-of-week`, each field a list of `*`, numbers,
ranges (`1-5`) and steps (`*/15`, `10-50/10`). Sunday is 0 or 7. As in Vixie cron,
when both the day of the month and the day of the week are restricted a day matches
when either of them does. Four macros are known (`@hourly`, `@daily`, `@weekly`,
`@monthly`) and `@once` means a single run: it has no next run.

Everything is in UTC. A schedule that fires in the evening in one season and the
night in another is a thing a small MSP does not want from a quiet background job.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

ONCE = "@once"
MAX_LENGTH = 64
MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
}
# Eight years of days: every date, 29 February included, comes up inside it.
SEARCH_DAYS = 366 * 8
FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of the month", 1, 31),
    ("month", 1, 12),
    ("day of the week", 0, 7),
)


class CronError(ValueError):
    """The text is not a cron expression this application understands."""


@dataclass(frozen=True)
class Cron:
    """A parsed expression: the allowed values of each field."""

    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: tuple[int, ...]
    months: tuple[int, ...]
    weekdays: tuple[int, ...]
    days_any: bool
    weekdays_any: bool


def _number(text: str, name: str) -> int:
    if not text.isascii() or not text.isdecimal() or len(text) > 3:
        raise CronError(f"the {name} field has {text!r}, which is not a number")
    return int(text)


def _parse_part(part: str, name: str, low: int, high: int) -> range:
    base, slash, step_text = part.partition("/")
    step = _number(step_text, name) if slash else 1
    if step < 1:
        raise CronError(f"the {name} field has a step below 1")
    if base == "*":
        first, last = low, high
    elif "-" in base:
        first_text, _, last_text = base.partition("-")
        first, last = _number(first_text, name), _number(last_text, name)
    else:
        first = _number(base, name)
        last = high if slash else first
    if not low <= first <= last <= high:
        raise CronError(f"the {name} field must stay between {low} and {high}")
    return range(first, last + 1, step)


def _parse_field(text: str, name: str, low: int, high: int) -> tuple[int, ...]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"the {name} field has an empty part")
        values.update(_parse_part(part, name, low, high))
    return tuple(sorted(values))


def parse_cron(text: str) -> Cron:
    """Parse an expression. Raises CronError with a readable message."""
    cleaned = text.strip()
    if len(cleaned) > MAX_LENGTH:
        raise CronError(f"the expression is longer than {MAX_LENGTH} characters")
    cleaned = MACROS.get(cleaned, cleaned)
    fields = cleaned.split()
    if len(fields) != len(FIELDS):
        raise CronError("a cron expression has five fields")
    parsed = [
        _parse_field(value, name, low, high)
        for value, (name, low, high) in zip(fields, FIELDS, strict=True)
    ]
    weekdays = tuple(sorted({day % 7 for day in parsed[4]}))
    return Cron(
        minutes=parsed[0],
        hours=parsed[1],
        days=parsed[2],
        months=parsed[3],
        weekdays=weekdays,
        days_any=fields[2].startswith("*"),
        weekdays_any=fields[4].startswith("*"),
    )


def _day_matches(cron: Cron, day: datetime) -> bool:
    in_month = day.day in cron.days
    in_week = (day.weekday() + 1) % 7 in cron.weekdays
    if cron.days_any or cron.weekdays_any:
        return in_month and in_week
    return in_month or in_week


def next_run(cron: Cron, after: datetime) -> datetime:
    """The first matching minute strictly after `after` (an aware time), in UTC."""
    if after.tzinfo is None:
        raise ValueError("the time must carry a time zone")
    start = after.astimezone(UTC).replace(second=0, microsecond=0)
    start += timedelta(minutes=1)
    for offset in range(SEARCH_DAYS):
        day = start + timedelta(days=offset)
        if day.month not in cron.months or not _day_matches(cron, day):
            continue
        for hour in cron.hours:
            for minute in cron.minutes:
                moment = day.replace(hour=hour, minute=minute)
                if moment >= start:
                    return moment
    raise CronError("the expression never matches a real date")


def is_once(text: str) -> bool:
    return text.strip() == ONCE


def validate_cron(text: str) -> str:
    """The expression as it is stored (trimmed), or CronError. `@once` is valid.

    An expression that reads well but never meets a real date (`0 0 31 2 *`) is
    refused too: it has no next run, so a schedule on it could never be started.
    """
    cleaned = text.strip()
    if cleaned != ONCE:
        next_run(parse_cron(cleaned), datetime.now(UTC))
    return cleaned


def next_run_for(text: str, after: datetime) -> datetime | None:
    """The next run of a stored expression after `after`; None for `@once`."""
    if is_once(text):
        return None
    return next_run(parse_cron(text), after)
