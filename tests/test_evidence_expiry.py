"""Freshness, expiry and retention dates, in exact arithmetic."""

import random
from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest

from app.evidence.assurance import Assurance
from app.evidence.expiry import (
    Freshness,
    add_months,
    days_left,
    default_max_age,
    expired_at,
    freshness_factor,
    freshness_state,
    item_age,
    pack_expires_at,
    raw_expires_at,
    reminder_thresholds_due,
    stale_after,
    state_of_item,
)

MAX_AGE = timedelta(days=35)
CAPTURED = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
ONE_MICROSECOND = timedelta(microseconds=1)


def test_at_exactly_the_maximum_age_the_evidence_is_still_current() -> None:
    assert freshness_factor(MAX_AGE, MAX_AGE) == Fraction(1)
    assert freshness_state(MAX_AGE, MAX_AGE) is Freshness.CURRENT


def test_just_after_the_maximum_age_the_evidence_is_stale_and_decays() -> None:
    assert freshness_state(MAX_AGE + ONE_MICROSECOND, MAX_AGE) is Freshness.STALE
    assert Fraction(0) < freshness_factor(MAX_AGE + ONE_MICROSECOND, MAX_AGE) < 1


def test_halfway_between_the_maximum_and_twice_it_the_factor_is_one_half() -> None:
    assert freshness_factor(MAX_AGE * 3 / 2, MAX_AGE) == Fraction(1, 2)


def test_at_exactly_twice_the_maximum_age_the_evidence_is_expired() -> None:
    assert freshness_factor(2 * MAX_AGE, MAX_AGE) == Fraction(0)
    assert freshness_state(2 * MAX_AGE, MAX_AGE) is Freshness.EXPIRED


def test_just_before_twice_the_maximum_age_it_is_still_stale() -> None:
    age = 2 * MAX_AGE - ONE_MICROSECOND
    assert freshness_state(age, MAX_AGE) is Freshness.STALE
    assert freshness_factor(age, MAX_AGE) > 0


def test_a_new_item_has_full_freshness() -> None:
    assert freshness_factor(timedelta(0), MAX_AGE) == Fraction(1)


def test_a_non_positive_maximum_age_is_refused() -> None:
    for bad in (timedelta(0), timedelta(days=-1)):
        with pytest.raises(ValueError, match="positive"):
            freshness_factor(MAX_AGE, bad)
        with pytest.raises(ValueError, match="positive"):
            freshness_state(MAX_AGE, bad)


def test_the_factor_never_rises_with_age_and_stays_between_zero_and_one() -> None:
    generator = random.Random(7)
    seconds = sorted(generator.randrange(0, 3 * 35 * 86400) for _ in range(500))
    ages = [timedelta(seconds=value) for value in seconds]
    factors = [freshness_factor(age, MAX_AGE) for age in ages]
    assert all(0 <= factor <= 1 for factor in factors)
    assert factors == sorted(factors, reverse=True)


def test_stale_and_expired_moments_follow_the_capture_time() -> None:
    assert stale_after(CAPTURED, MAX_AGE) == CAPTURED + timedelta(days=35)
    assert expired_at(CAPTURED, MAX_AGE) == CAPTURED + timedelta(days=70)


def test_the_state_of_a_stored_item_uses_its_own_maximum_age() -> None:
    expires = stale_after(CAPTURED, MAX_AGE)
    just_after = expires + ONE_MICROSECOND
    assert state_of_item(CAPTURED, expires, expires) is Freshness.CURRENT
    assert state_of_item(CAPTURED, expires, just_after) is Freshness.STALE
    assert state_of_item(CAPTURED, expires, expires + MAX_AGE) is Freshness.EXPIRED


def test_an_item_captured_after_the_asked_time_has_age_zero() -> None:
    assert item_age(CAPTURED, CAPTURED - timedelta(days=1)) == timedelta(0)
    assert item_age(CAPTURED, CAPTURED + timedelta(days=3)) == timedelta(days=3)


def test_each_assurance_level_has_a_default_maximum_age() -> None:
    assert default_max_age(Assurance.AUTOMATIC_EXPORT) == timedelta(days=35)
    assert default_max_age(Assurance.MANUAL_ARTEFACT) == timedelta(days=365)
    assert default_max_age(Assurance.ATTESTATION) == timedelta(days=365)


def test_assurance_quality_factors_and_labels() -> None:
    assert Assurance.AUTOMATIC_EXPORT.quality == Fraction(1)
    assert Assurance.MANUAL_ARTEFACT.quality == Fraction(9, 10)
    assert Assurance.ATTESTATION.quality == Fraction(3, 5)
    labels = {level.label for level in Assurance}
    assert len(labels) == 3


def test_days_left_rounds_down_and_goes_negative_after_expiry() -> None:
    expires = CAPTURED + timedelta(days=10)
    assert days_left(expires, CAPTURED) == 10
    assert days_left(expires, CAPTURED + timedelta(hours=1)) == 9
    assert days_left(expires, expires) == 0
    assert days_left(expires, expires + timedelta(seconds=1)) == -1


def test_reminders_become_due_at_each_threshold() -> None:
    expires = CAPTURED + timedelta(days=40)
    assert reminder_thresholds_due(expires, CAPTURED) == ()
    assert reminder_thresholds_due(expires, expires - timedelta(days=30)) == (30,)
    assert reminder_thresholds_due(expires, expires - timedelta(days=7)) == (30, 7)
    assert reminder_thresholds_due(expires, expires - timedelta(hours=1)) == (30, 7, 0)
    assert reminder_thresholds_due(expires, expires) == (30, 7, 0)


def test_raw_expiry_is_none_without_retention() -> None:
    assert raw_expires_at(CAPTURED, 0) is None
    assert raw_expires_at(CAPTURED, 7) == CAPTURED + timedelta(days=7)
    assert raw_expires_at(CAPTURED, 35) == CAPTURED + timedelta(days=35)
    with pytest.raises(ValueError, match="negative"):
        raw_expires_at(CAPTURED, -1)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (datetime(2026, 1, 31, tzinfo=UTC), 1, datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2028, 1, 31, tzinfo=UTC), 1, datetime(2028, 2, 29, tzinfo=UTC)),
        (datetime(2026, 11, 15, tzinfo=UTC), 2, datetime(2027, 1, 15, tzinfo=UTC)),
        (
            datetime(2026, 10, 17, 9, 5, tzinfo=UTC),
            25,
            datetime(2028, 11, 17, 9, 5, tzinfo=UTC),
        ),
        (datetime(2026, 12, 31, tzinfo=UTC), 12, datetime(2027, 12, 31, tzinfo=UTC)),
    ],
)
def test_months_are_calendar_months_clamped_to_the_month_end(
    start: datetime, months: int, expected: datetime
) -> None:
    assert add_months(start, months) == expected


def test_pack_retention_defaults_to_25_months_and_needs_at_least_one() -> None:
    created = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    assert pack_expires_at(created, 25) == datetime(2028, 11, 17, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="at least one month"):
        pack_expires_at(created, 0)
