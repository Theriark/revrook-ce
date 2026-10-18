"""The scoring engine around its arithmetic (phase 6).

Gate caps, bands, display rounding, the refusal of a naive time and of inputs that
would leave a control out silently, the entry point over real evidence, and the
rule that the engine uses no float.
"""

import ast
from dataclasses import replace
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from app.checks.engine import evaluate_all
from app.checks.library import load_library
from app.checks.model import Evidence
from app.scoring import display, engine, model, snapshot
from app.scoring.display import format_fixed, headline, percent
from app.scoring.engine import (
    band_of,
    control_inputs,
    domain_weights,
    score_evidence,
    score_inputs,
    score_results,
)
from app.scoring.model import DEFAULT_THRESHOLDS, ControlInput, DomainWeight
from tools.score_inputs import AS_OF

LIBRARY = load_library()
DOMAIN_X = [DomainWeight("X", 100)]


def item(
    control_id: str,
    status: Any = "pass",
    age_days: float | None = 0,
    *,
    gate: bool = False,
    weight: int = 2,
    limit: int | None = 7,
    quality: Fraction = Fraction(1),
) -> ControlInput:
    at = None if age_days is None else AS_OF - timedelta(days=age_days)
    return ControlInput(control_id, "X", weight, gate, status, quality, at, limit)


# --- gate caps -----------------------------------------------------------------------

GATE_CASES = [
    ("fail", 0, 49, "fail"),
    ("unknown", None, 49, "unknown"),
    ("pass", 14, 49, "expired"),
    ("partial", 14, 49, "expired"),
    ("pass", 100, 49, "expired"),
    ("partial", 0, 69, "partial"),
    ("partial", 10, 69, "partial"),
    ("pass", 10, 69, "stale"),
    ("pass", 7.5, 69, "stale"),
    ("pass", 7, None, None),
    ("pass", 0, None, None),
    ("na", None, None, None),
]


@pytest.mark.parametrize(("status", "age", "limit", "reason"), GATE_CASES)
def test_a_gate_control_caps_the_score_by_its_status_and_its_age(
    status: str, age: float | None, limit: int | None, reason: str | None
) -> None:
    quality = Fraction(0 if status in ("unknown", "na") else 1)
    gate = item("PC-X-01", status, age, gate=True, quality=quality)
    other = item("PC-X-02")
    result = score_inputs([gate, other], DOMAIN_X, AS_OF)
    if limit is None:
        assert result.cap is None
        return
    assert result.cap is not None
    assert (result.cap.control_id, result.cap.limit) == ("PC-X-01", limit)
    assert result.cap.reason == reason
    assert result.score <= limit


def test_the_lowest_cap_wins_and_the_first_gate_wins_a_tie() -> None:
    partial = item("PC-X-01", "partial", gate=True)
    failed = item("PC-X-02", "fail", gate=True)
    other_failed = item("PC-X-03", "fail", gate=True)
    cap = score_inputs([partial, failed, other_failed], DOMAIN_X, AS_OF).cap
    assert cap is not None and (cap.control_id, cap.limit) == ("PC-X-02", 49)
    cap = score_inputs([failed, partial], DOMAIN_X, AS_OF).cap
    assert cap is not None and cap.control_id == "PC-X-02"


def test_a_cap_above_the_score_is_kept_but_does_not_bind() -> None:
    gate = item("PC-X-01", "partial", gate=True, weight=1)
    low = item("PC-X-02", "fail", weight=9)
    result = score_inputs([gate, low], DOMAIN_X, AS_OF)
    assert result.raw == 5 and result.score == 5
    assert result.cap is not None and result.cap.limit == 69
    assert not result.capped
    assert "capped" not in headline(result)


def test_a_not_applicable_gate_does_not_cap_the_score() -> None:
    gate = item("PC-X-01", "na", None, gate=True, quality=Fraction(0))
    result = score_inputs([gate, item("PC-X-02")], DOMAIN_X, AS_OF)
    assert result.cap is None and result.score == 100


def test_a_non_gate_failure_never_caps_the_score() -> None:
    result = score_inputs([item("PC-X-01", "fail"), item("PC-X-02")], DOMAIN_X, AS_OF)
    assert result.cap is None and result.score == 50


# --- bands and display ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (Fraction(100), "Strong"),
        (Fraction(85), "Strong"),
        (Fraction(8499, 100), "Good"),
        (Fraction(70), "Good"),
        (Fraction(6999, 100), "Fair"),
        (Fraction(50), "Fair"),
        (Fraction(4999, 100), "Weak"),
        (Fraction(30), "Weak"),
        (Fraction(2999, 100), "Critical"),
        (Fraction(0), "Critical"),
    ],
)
def test_the_bands_start_at_85_70_50_and_30(score: Fraction, band: str) -> None:
    assert band_of(score, DEFAULT_THRESHOLDS) == band


def test_the_band_follows_the_exact_score_and_not_its_rounded_display() -> None:
    score = Fraction(8496, 100)
    assert format_fixed(score) == "85.0"
    assert band_of(score, DEFAULT_THRESHOLDS) == "Good"


@pytest.mark.parametrize(
    ("value", "places", "text"),
    [
        (Fraction(895, 10), 1, "89.5"),
        (Fraction(5, 100), 1, "0.1"),
        (Fraction(4, 100), 1, "0.0"),
        (Fraction(7), 1, "7.0"),
        (Fraction(-3, 2), 1, "-1.5"),
        (Fraction(-1, 100), 1, "0.0"),
        (Fraction(99, 100), 2, "0.99"),
        (Fraction(1, 2), 0, "1"),
        (Fraction(-1, 2), 0, "-1"),
        (Fraction(0), 0, "0"),
    ],
)
def test_a_value_is_rounded_half_away_from_zero(
    value: Fraction, places: int, text: str
) -> None:
    assert format_fixed(value, places) == text


def test_coverage_is_shown_as_whole_percent() -> None:
    assert percent(Fraction(70, 99)) == "71"
    assert percent(Fraction(97, 98)) == "99"
    assert percent(Fraction(1)) == "100"


# --- what the engine refuses ---------------------------------------------------------


def test_a_naive_pack_date_is_refused_with_a_clear_error() -> None:
    with pytest.raises(ValueError, match="as_of must carry a timezone"):
        score_inputs([item("PC-X-01")], DOMAIN_X, datetime(2026, 10, 17, 8, 0))


def test_a_naive_evidence_time_is_refused() -> None:
    naive = replace(item("PC-X-01"), evidence_at=datetime(2026, 10, 17, 8, 0))
    with pytest.raises(ValueError, match="evidence time must carry a timezone"):
        score_inputs([naive], DOMAIN_X, AS_OF)


def test_the_entry_points_refuse_a_naive_pack_date_with_a_value_error() -> None:
    evidence = Evidence(as_of=datetime(2026, 10, 17, 8, 0))
    with pytest.raises(ValueError, match="as_of must carry a timezone"):
        score_evidence(LIBRARY, evidence)
    with pytest.raises(ValueError, match="as_of must carry a timezone"):
        score_results(LIBRARY, {}, datetime(2026, 10, 17, 8, 0))


def test_a_control_with_no_result_is_an_error_and_not_a_zero() -> None:
    with pytest.raises(ValueError, match="PC-ACC-01: the control has no result"):
        control_inputs(LIBRARY, {})


@pytest.mark.parametrize(
    ("controls", "domains", "message"),
    [
        ([item("PC-X-01"), item("PC-X-01")], DOMAIN_X, "a control is listed twice"),
        ([item("PC-X-01")], DOMAIN_X + DOMAIN_X, "a domain is listed twice"),
        ([item("PC-X-01")], [DomainWeight("Y", 100)], "there is no domain X"),
        ([item("PC-X-01", weight=-1)], DOMAIN_X, "weight or quality out of range"),
        (
            [item("PC-X-01", quality=Fraction(3, 2))],
            DOMAIN_X,
            "weight or quality out of range",
        ),
        ([item("PC-X-01")], [DomainWeight("X", -1)], "a domain weight is negative"),
    ],
)
def test_inputs_that_would_leave_a_control_out_silently_are_refused(
    controls: list[ControlInput], domains: list[DomainWeight], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        score_inputs(controls, domains, AS_OF)


def test_evidence_dated_after_the_pack_date_counts_as_age_zero() -> None:
    future = item("PC-X-01", "pass", -3)
    scored = engine.score_control(future, AS_OF)
    assert scored.freshness == 1 and not scored.stale


# --- the entry point over real evidence ---------------------------------------------


def test_no_evidence_at_all_scores_zero_with_the_three_gates_unknown() -> None:
    result = score_evidence(LIBRARY, Evidence(as_of=AS_OF))
    assert result.raw == 0 and result.score == 0
    assert result.coverage == 0 and result.insufficient
    assert result.cap is not None
    assert (result.cap.control_id, result.cap.reason) == ("PC-ACC-01", "unknown")
    assert result.band == "Insufficient evidence" and result.best_case is None
    assert result.upper == 100
    assert headline(result) == (
        "Insufficient evidence: lower bound 0.0, evidence coverage 0 percent"
    )
    assert len(result.controls) == 51 and len(result.domains) == 8


def test_scoring_the_results_equals_scoring_the_evidence() -> None:
    evidence = Evidence(as_of=AS_OF)
    by_evidence = score_evidence(LIBRARY, evidence)
    by_results = score_results(LIBRARY, evaluate_all(LIBRARY, evidence), AS_OF)
    assert by_evidence == by_results
    assert domain_weights(LIBRARY)[0] == DomainWeight("ACC", 22)


# --- exact arithmetic ---------------------------------------------------------------


def test_every_number_the_engine_returns_is_exact() -> None:
    result = score_evidence(LIBRARY, Evidence(as_of=AS_OF))
    numbers: list[Any] = [result.raw, result.score, result.coverage, result.upper]
    for scored in result.controls:
        numbers += [scored.quality, scored.freshness, scored.score, scored.contribution]
    for domain in result.domains:
        numbers += [domain.earned, domain.score]
    assert all(not isinstance(number, float) for number in numbers)


@pytest.mark.parametrize("module", [model, engine, display, snapshot])
def test_the_scoring_code_has_no_float_in_it(module: Any) -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float), node.lineno
        if isinstance(node, ast.Name):
            assert node.id != "float", node.lineno
