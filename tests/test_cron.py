"""The cron expressions of the schedule table. No database is needed."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.worker.cron import (
    ONCE,
    CronError,
    is_once,
    next_run,
    next_run_for,
    parse_cron,
    validate_cron,
)


def at(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# 2026-10-19 is a Monday.
MONDAY = at(2026, 10, 19)


@pytest.mark.parametrize(
    ("text", "after", "expected"),
    [
        # Strictly after: a run at 06:00 is not due again at 06:00.
        ("0 6 * * *", at(2026, 10, 19, 5, 59), at(2026, 10, 19, 6, 0)),
        ("0 6 * * *", at(2026, 10, 19, 6, 0), at(2026, 10, 20, 6, 0)),
        ("*/15 * * * *", at(2026, 10, 19, 12, 7), at(2026, 10, 19, 12, 15)),
        ("*/15 * * * *", at(2026, 10, 19, 12, 45), at(2026, 10, 19, 13, 0)),
        ("10-50/20 * * * *", at(2026, 10, 19, 12, 11), at(2026, 10, 19, 12, 30)),
        ("1,5,9 * * * *", at(2026, 10, 19, 12, 5), at(2026, 10, 19, 12, 9)),
        ("30 3 * * 1", at(2026, 10, 19, 4, 0), at(2026, 10, 26, 3, 30)),
        ("0 0 1 * *", at(2026, 10, 19), at(2026, 11, 1)),
        ("0 0 1 1 *", at(2026, 10, 19), at(2027, 1, 1)),
        # 29 February comes up in the next leap year.
        ("0 0 29 2 *", at(2026, 10, 19), at(2028, 2, 29)),
        # Both the day of the month and the day of the week: either one matches.
        ("0 0 13 * 5", at(2026, 10, 19), at(2026, 10, 23)),
        ("0 0 25 * 5", at(2026, 10, 19), at(2026, 10, 23)),
        ("0 0 21 * 5", at(2026, 10, 19), at(2026, 10, 21)),
        # The macros.
        ("@hourly", at(2026, 10, 19, 12, 30), at(2026, 10, 19, 13, 0)),
        ("@daily", at(2026, 10, 19, 12, 30), at(2026, 10, 20, 0, 0)),
        ("@weekly", MONDAY, at(2026, 10, 25)),
        ("@monthly", MONDAY, at(2026, 11, 1)),
    ],
)
def test_the_next_run_is_the_first_matching_minute_after(
    text: str, after: datetime, expected: datetime
) -> None:
    assert next_run(parse_cron(text), after) == expected
    assert next_run_for(text, after) == expected


def test_seconds_are_ignored_and_the_result_is_on_the_minute() -> None:
    after = datetime(2026, 10, 19, 6, 0, 59, 999999, tzinfo=UTC)
    assert next_run_for("* * * * *", after) == at(2026, 10, 19, 6, 1)


def test_a_time_in_another_zone_is_read_in_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    after = datetime(2026, 10, 19, 23, 30, tzinfo=plus_two)  # 21:30 UTC
    assert next_run_for("0 22 * * *", after) == at(2026, 10, 19, 22, 0)
    assert next_run_for("0 22 * * *", after).tzinfo == UTC


def test_sunday_is_0_and_7() -> None:
    assert parse_cron("0 0 * * 7").weekdays == (0,)
    assert parse_cron("0 0 * * 0").weekdays == (0,)
    assert parse_cron("0 0 * * 5-7").weekdays == (0, 5, 6)


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        next_run(parse_cron("* * * * *"), datetime(2026, 10, 19, 6, 0))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * 32 * *",
        "* * * 13 *",
        "* * * * 8",
        "a * * * *",
        "*/0 * * * *",
        "*/x * * * *",
        "5-1 * * * *",
        "1,,2 * * * *",
        "-1 * * * *",
        "1" * 70,
        "@yearly",
        "@once",
    ],
)
def test_an_expression_that_cannot_be_read_is_refused(text: str) -> None:
    with pytest.raises(CronError):
        parse_cron(text)


def test_an_expression_that_never_matches_a_real_date_is_refused() -> None:
    with pytest.raises(CronError, match="never matches"):
        next_run(parse_cron("0 0 31 4 *"), MONDAY)


def test_once_has_no_next_run() -> None:
    assert is_once(" @once ")
    assert not is_once("@daily")
    assert next_run_for(ONCE, MONDAY) is None
    assert validate_cron("  @once ") == ONCE
    assert validate_cron(" 0 6 * * * ") == "0 6 * * *"
    with pytest.raises(CronError):
        validate_cron("every day")
