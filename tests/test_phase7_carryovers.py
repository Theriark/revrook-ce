"""Carry-overs from the independent checks of phase 6 (THE-309 and THE-310).

* D1: the scoring engine range-checks a maximum age before it does any date
  arithmetic: a negative one and one beyond 36,500 days are a ValueError, and a
  value that would overflow a timedelta never gets that far.
* D2: the snapshot reader matches a fraction against ^-?[0-9]+/[0-9]+$ before it
  builds a Fraction, so exponent text such as 1e999999999 is refused at once, and
  every threshold, status and whole number it reads is range-checked. Whatever goes
  wrong inside is a SnapshotError, never a KeyError, OverflowError or
  RecursionError, and never a long wait.
* D3: a coverage just below the 0.60 minimum is Insufficient evidence.

The independent recomputation of clients A, B and C is tests/independent/.
"""

import hashlib
import json
import time
from collections.abc import Callable
from fractions import Fraction
from typing import Any

import pytest

from app.scoring.engine import MAX_AGE_DAYS, score_inputs
from app.scoring.model import DEFAULT_THRESHOLDS, ControlInput, DomainWeight
from app.scoring.snapshot import SnapshotError, parse_snapshot, regenerate
from tools.make_scoring_golden import GOLDEN
from tools.score_inputs import AS_OF

DOMAIN_X = [DomainWeight("X", 100)]
# Seconds. Generous on purpose: each refusal below takes microseconds, while building
# Fraction("1e999999999") would take far longer than any test run.
BOUND = 5.0


def control(
    control_id: str,
    status: Any = "pass",
    limit: int | None = 7,
    quality: Fraction = Fraction(1),
) -> ControlInput:
    at = None if status == "unknown" else AS_OF
    return ControlInput(control_id, "X", 1, False, status, quality, at, limit)


# --- D1: the maximum age ------------------------------------------------------------


@pytest.mark.parametrize("limit", [-1, MAX_AGE_DAYS + 1, 10**9, 10**12, 10**30])
def test_an_absurd_maximum_age_is_a_value_error(limit: int) -> None:
    with pytest.raises(ValueError, match="max_age_days must be 0 to 36500"):
        score_inputs([control("PC-X-01", limit=limit)], DOMAIN_X, AS_OF)


@pytest.mark.parametrize("limit", [0, 1, MAX_AGE_DAYS])
def test_the_ends_of_the_range_of_a_maximum_age_are_scored(limit: int) -> None:
    result = score_inputs([control("PC-X-01", limit=limit)], DOMAIN_X, AS_OF)
    assert result.score == 100


def test_a_control_without_a_maximum_age_is_still_fresh() -> None:
    result = score_inputs([control("PC-X-01", limit=None)], DOMAIN_X, AS_OF)
    assert result.score == 100


# --- D2: the snapshot reader --------------------------------------------------------


def document() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(GOLDEN.read_bytes())
    return loaded


def canonical(value: dict[str, Any]) -> bytes:
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return text.encode("ascii")


def resign(changed: dict[str, Any]) -> bytes:
    """The document with a valid digest again, so that only its content is wrong."""
    body = {key: value for key, value in changed.items() if key != "sha256"}
    signed = {**body, "sha256": hashlib.sha256(canonical(body)).hexdigest()}
    return canonical(signed) + b"\n"


def set_path(*path: Any, value: Any) -> Callable[[dict[str, Any]], None]:
    def change(stored: dict[str, Any]) -> None:
        target: Any = stored
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value

    return change


def mutated(change: Callable[[dict[str, Any]], None]) -> bytes:
    stored = document()
    change(stored)
    return resign(stored)


def refused(data: bytes, message: str) -> None:
    """Both entry points refuse the snapshot with a SnapshotError, quickly."""
    started = time.perf_counter()
    with pytest.raises(SnapshotError, match=message):
        parse_snapshot(data)
    with pytest.raises(SnapshotError, match="cannot be read"):
        regenerate(data)
    assert time.perf_counter() - started < BOUND


def quality(value: Any) -> bytes:
    return mutated(set_path("controls", 0, "quality", value=value))


def thresholds(name: str, value: Any) -> bytes:
    return mutated(set_path("thresholds", name, value=value))


def weight(value: Any) -> bytes:
    return mutated(set_path("controls", 0, "weight", value=value))


def max_age(value: Any) -> bytes:
    return mutated(set_path("controls", 0, "max_age_days", value=value))


WHOLE = "whole number from 0 to 1000000"
BAD_FRACTIONS = [
    ("exponent", "1e999999999"),
    ("negative-exponent", "-1e999999999"),
    ("small-exponent", "1e2"),
    ("decimal", "0.5"),
    ("no-denominator", "1"),
    ("two-slashes", "1/2/3"),
    ("leading-space", " 1/2"),
    ("trailing-newline", "1/1\n"),
    ("plus-sign", "+1/2"),
    ("other-digits", "١/٢"),
    ("very-long", "1/" + "9" * 5000),
    ("not-lowest", "2/4"),
]


@pytest.mark.parametrize(
    "text", [text for _, text in BAD_FRACTIONS], ids=[n for n, _ in BAD_FRACTIONS]
)
def test_a_fraction_that_is_not_plain_n_over_d_is_refused_at_once(text: str) -> None:
    refused(quality(text), "lowest terms")
    refused(thresholds("min_coverage", text), "lowest terms")


def test_a_zero_denominator_is_a_snapshot_error() -> None:
    refused(quality("1/0"), "Fraction")


@pytest.mark.parametrize("text", ["3/2", "-1/2"])
def test_a_quality_outside_zero_to_one_is_refused(text: str) -> None:
    refused(quality(text), "weight or quality out of range")


@pytest.mark.parametrize("text", ["3/2", "-1/5", "2/1"])
def test_a_threshold_share_outside_zero_to_one_is_refused(text: str) -> None:
    refused(thresholds("min_coverage", text), "not between 0 and 1")
    refused(thresholds("na_flag_above", text), "not between 0 and 1")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (thresholds("cap_fail", 101), "above the highest score"),
        (thresholds("cap_partial", 70000), "above the highest score"),
        (thresholds("cap_fail", -1), WHOLE),
        (thresholds("cap_partial", 10**30), WHOLE),
        (thresholds("cap_fail", True), "whole number was expected"),
        (thresholds("cap_fail", "49"), "whole number was expected"),
        (thresholds("bands", []), "from the best down"),
        (thresholds("bands", [["Weak", 30], ["Strong", 85]]), "from the best down"),
        (thresholds("bands", [["", 85]]), "a name must have"),
        (thresholds("bands", [["x" * 65, 85]]), "a name must have"),
        (thresholds("bands", [["Strong", 85, 1]]), "name and the lowest score"),
        (thresholds("bands", [["Strong", 101]]), "above the highest score"),
        (thresholds("bands", ["Strong"]), "index|list was expected"),
        (thresholds("bands", {}), "list was expected"),
        (thresholds("lowest_band", 5), "text was expected"),
        (thresholds("lowest_band", ""), "a name must have"),
        (thresholds("insufficient_band", "x" * 65), "a name must have"),
    ],
)
def test_a_threshold_that_is_out_of_range_or_the_wrong_kind_is_refused(
    data: bytes, message: str
) -> None:
    refused(data, message)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (weight(10**30), WHOLE),
        (weight(-1), WHOLE),
        (max_age(-1), WHOLE),
        (max_age(10**12), WHOLE),
        (max_age(MAX_AGE_DAYS + 1), "max_age_days must be 0 to 36500"),
        (max_age("7"), "whole number was expected"),
        (
            mutated(set_path("domains", 0, "weight", value=10**30)),
            WHOLE,
        ),
        (
            mutated(set_path("controls", 0, "status", value=["pass"])),
            "text was expected",
        ),
        (
            mutated(set_path("controls", 0, "status", value="PASS")),
            "not a status",
        ),
        (
            mutated(set_path("controls", 1, "id", value="PC-ACC-01")),
            "a control is listed twice",
        ),
        (
            mutated(set_path("controls", 0, "domain", value="ZZZ")),
            "there is no domain ZZZ",
        ),
    ],
)
def test_a_value_that_is_out_of_range_or_the_wrong_kind_is_refused(
    data: bytes, message: str
) -> None:
    refused(data, message)


def test_a_snapshot_nested_without_end_is_a_snapshot_error() -> None:
    nested = b"[" * 200_000 + b"]" * 200_000
    started = time.perf_counter()
    with pytest.raises(SnapshotError, match="cannot be read"):
        parse_snapshot(nested)
    assert time.perf_counter() - started < BOUND


def test_the_golden_snapshot_is_still_read() -> None:
    inputs = parse_snapshot(GOLDEN.read_bytes())
    assert inputs.thresholds == DEFAULT_THRESHOLDS
    assert len(inputs.controls) == 51


# --- D3: coverage around the minimum ------------------------------------------------


def fleet(covered: int, unknown: int) -> list[ControlInput]:
    """Controls of weight 1: some passing with fresh evidence, some unknown."""
    found = [control(f"PC-X-{number:02d}") for number in range(covered)]
    for number in range(covered, covered + unknown):
        missing = control(f"PC-X-{number:02d}", "unknown", quality=Fraction(0))
        found.append(missing)
    return found


def test_coverage_just_below_the_minimum_is_insufficient_evidence() -> None:
    result = score_inputs(fleet(29, 21), DOMAIN_X, AS_OF)
    assert result.coverage == Fraction(29, 50) < DEFAULT_THRESHOLDS.min_coverage
    assert result.insufficient
    assert result.band == DEFAULT_THRESHOLDS.insufficient_band
    assert result.best_case is None
    assert result.score == 58


def test_coverage_exactly_at_the_minimum_is_enough() -> None:
    result = score_inputs(fleet(30, 20), DOMAIN_X, AS_OF)
    assert result.coverage == DEFAULT_THRESHOLDS.min_coverage == Fraction(3, 5)
    assert not result.insufficient
    assert result.band == "Fair"
    assert result.best_case == 100


def test_coverage_just_above_the_minimum_is_enough() -> None:
    result = score_inputs(fleet(31, 19), DOMAIN_X, AS_OF)
    assert result.coverage == Fraction(31, 50)
    assert not result.insufficient
    assert result.band == "Fair"
