"""The scoring vectors of phase-plan-3: clients A, B and C and the seven edge vectors.

The clients are in tests/scoring_vectors/clients.json. Their expected results were
worked out by hand (not by the engine) and are compared within 0.05 points. If a
hand vector were wrong the engine would not be bent to fit it: the discrepancy is
recorded, the vector corrected with its evidence and reported to R&D Lead.
"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from app.checks.engine import contribution, evaluate_all, evaluate_control
from app.checks.library import load_library
from app.checks.model import Evidence, ManualItem
from app.scoring.display import format_fixed, headline, percent
from app.scoring.engine import (
    control_inputs,
    domain_weights,
    freshness,
    score_control,
    score_inputs,
)
from app.scoring.model import ControlInput, DomainWeight, ScoreResult
from tools.score_inputs import AS_OF, client_spec, inputs_for, load_clients
from tools.vector_facts import build_evidence

LIBRARY = load_library()
DOMAINS = domain_weights(LIBRARY)
CLIENTS = load_clients()
TOLERANCE = Fraction(CLIENTS["tolerance"])
NAMES = ["A", "B", "C"]


def score_client(name: str) -> ScoreResult:
    spec = client_spec(LIBRARY, CLIENTS, name)
    return score_inputs(inputs_for(LIBRARY, spec), DOMAINS, AS_OF)


def close(actual: Fraction, expected: str) -> bool:
    return abs(actual - Fraction(Decimal(expected))) <= TOLERANCE


# --- clients A, B and C --------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_the_client_reproduces_the_hand_computed_report(name: str) -> None:
    expect = CLIENTS["clients"][name]["expect"]
    result = score_client(name)
    assert close(result.raw, expect["raw"]), float(result.raw)
    assert close(result.score, expect["score"]), float(result.score)
    assert result.best_case is not None
    assert close(result.best_case, expect["best_case"]), float(result.best_case)
    assert percent(result.coverage) == str(expect["coverage_percent"])
    assert result.band == expect["band"]
    assert not result.insufficient
    assert not result.na_flagged


@pytest.mark.parametrize("name", NAMES)
def test_the_domain_scores_match_the_hand_computation(name: str) -> None:
    expect = CLIENTS["clients"][name]["expect"]["domains"]
    found = {item.code: item for item in score_client(name).domains}
    for code, text in expect.items():
        score = found[code].score
        assert score is not None
        assert close(score, text), (code, float(score))


@pytest.mark.parametrize("name", NAMES)
def test_the_numbers_a_report_prints_are_exactly_the_expected_ones(name: str) -> None:
    expect = CLIENTS["clients"][name]["expect"]
    result = score_client(name)
    assert format_fixed(result.raw) == expect["raw"]
    assert format_fixed(result.score) == expect["score"]
    assert result.best_case is not None
    assert format_fixed(result.best_case) == expect["best_case"]


@pytest.mark.parametrize("name", NAMES)
def test_the_gate_cap_is_printed_beside_the_score(name: str) -> None:
    expect = CLIENTS["clients"][name]["expect"]["cap"]
    cap = score_client(name).cap
    if expect is None:
        assert cap is None
        return
    assert cap is not None
    assert (cap.control_id, cap.limit) == (expect["control"], expect["limit"])
    assert cap.reason == expect["reason"]


def test_client_a_covers_97_of_98_weight_and_has_no_gate_cap() -> None:
    result = score_client("A")
    assert result.coverage == Fraction(97, 98)
    assert result.cap is None and not result.capped
    assert result.na_weight == 1
    assert headline(result) == (
        "Score 89.5 (best case 90.5), band Strong, evidence coverage 99 percent"
    )


def test_client_b_covers_70_of_99_weight_and_its_gate_does_not_bind() -> None:
    result = score_client("B")
    assert result.coverage == Fraction(70, 99)
    assert result.cap is not None and not result.capped
    assert result.score == result.raw


def test_client_b_best_case_is_held_at_69_by_the_partial_gate() -> None:
    """Every unknown and stale control passing gives 70.5, but ACC-01 stays partial."""
    result = score_client("B")
    assert result.best_case == 69
    items = inputs_for(LIBRARY, client_spec(LIBRARY, CLIENTS, "B"))
    better = [
        replace(item, status="pass") if item.control_id == "PC-ACC-01" else item
        for item in items
    ]
    assert score_inputs(better, DOMAINS, AS_OF).upper > 70


def test_client_c_is_capped_from_86_6_to_49_by_a_failed_gate() -> None:
    result = score_client("C")
    assert result.capped
    assert format_fixed(result.raw) == "86.6"
    assert result.score == 49
    assert result.best_case == 49, "a failed gate is not missing evidence"
    assert result.coverage == 1
    assert headline(result) == (
        "Score 49.0 (best case 49.0), band Weak, evidence coverage 100 percent, "
        "capped from 86.6 by PC-ACC-02"
    )


def test_client_b_stale_controls_use_the_straight_line_freshness() -> None:
    by_id = {item.control_id: item for item in score_client("B").controls}
    assert by_id["PC-DEV-02"].freshness == Fraction(5, 7)
    assert by_id["PC-DEV-02"].contribution == Fraction(15, 7)
    assert by_id["PC-END-02"].contribution == Fraction(5, 7)
    for control_id in ("PC-BCK-01", "PC-BCK-02", "PC-BCK-04"):
        assert by_id[control_id].freshness == 0
        assert by_id[control_id].contribution == 0
    assert by_id["PC-BCK-03"].freshness == 1, "60 days is inside the 100 day limit"


# --- edge vector i: age exactly M, 1.5 M and 2 M -----------------------------------


@pytest.mark.parametrize("limit", [7, 35, 100, 365])
def test_age_m_gives_f_1_and_1_5_m_gives_one_half_and_2_m_gives_zero(
    limit: int,
) -> None:
    unit = timedelta(days=limit)
    assert freshness(timedelta(0), limit) == 1
    assert freshness(unit, limit) == 1
    assert freshness(unit * 3 // 2, limit) == Fraction(1, 2)
    assert freshness(unit * 2, limit) == 0
    assert freshness(unit * 3, limit) == 0
    assert freshness(unit + timedelta(microseconds=1), limit) < 1
    assert freshness(unit * 2 - timedelta(microseconds=1), limit) > 0


@pytest.mark.parametrize("limit", [7, 35, 100, 365])
def test_a_passing_control_earns_its_weight_times_f_at_the_boundaries(
    limit: int,
) -> None:
    unit = timedelta(days=limit)
    expected = [(unit, 3), (unit * 3 // 2, Fraction(3, 2)), (unit * 2, 0)]
    for age, earned in expected:
        item = ControlInput(
            "PC-X-01", "X", 3, False, "pass", Fraction(1), AS_OF - age, limit
        )
        scored = score_control(item, AS_OF)
        assert scored.contribution == earned
        assert scored.stale is (age > unit)


def test_evidence_without_a_time_or_a_limit_is_fresh() -> None:
    assert freshness(None, 7) == 1
    assert freshness(timedelta(days=900), None) == 1


# --- edge vector ii: a domain with every control not applicable ----------------------


def test_a_domain_of_not_applicable_controls_leaves_the_denominator() -> None:
    spec = client_spec(LIBRARY, CLIENTS, "A")
    for control in LIBRARY.in_domain("NET"):
        spec[control.id] = ["na", "0", None]
    for control in LIBRARY.in_domain("DEV"):
        spec[control.id] = ["fail", "1", 0]
    result = score_inputs(inputs_for(LIBRARY, spec), DOMAINS, AS_OF)
    assert result.dropped_domains == ("NET",)
    by_code = {item.code: item for item in result.domains}
    assert by_code["NET"].score is None
    assert by_code["DEV"].score == 0
    kept = [item for item in result.domains if item.score is not None]
    assert sum(item.weight for item in kept) == 94, "100 less the 6 of NET"
    total = Fraction(0)
    for item in kept:
        assert item.score is not None
        total += item.weight * item.score
    assert result.raw == total / 94


def test_all_controls_not_applicable_leaves_no_score_and_no_coverage() -> None:
    spec = {item.id: ["na", "0", None] for item in LIBRARY.controls}
    result = score_inputs(inputs_for(LIBRARY, spec), DOMAINS, AS_OF)
    assert result.raw == 0 and result.score == 0 and result.coverage == 0
    assert result.insufficient and result.na_flagged
    assert len(result.dropped_domains) == 8


# --- edge vector iii: a gate that is unknown caps the score at 49 --------------------


def test_a_gate_unknown_caps_the_score_at_49_even_when_the_overall_is_95() -> None:
    spec = {item.id: ["pass", "1", 0] for item in LIBRARY.controls}
    spec["PC-BCK-01"] = ["unknown", "0", None]
    for control_id in ("PC-GOV-01", "PC-LOG-02"):
        spec[control_id] = ["partial", "1", 0]
    result = score_inputs(inputs_for(LIBRARY, spec), DOMAINS, AS_OF)
    assert Fraction(94) < result.raw < Fraction(96), float(result.raw)
    assert result.score == 49
    assert result.capped
    assert result.cap is not None
    assert (result.cap.control_id, result.cap.reason) == ("PC-BCK-01", "unknown")
    assert result.band == "Weak"


# --- edge vector iv: a partial at q = 0.9 on a weight 2 control ----------------------


def test_a_partial_at_quality_nine_tenths_on_a_weight_2_control_gives_0_9() -> None:
    control = LIBRARY.control("PC-GOV-05")
    assert control.weight == 2
    manual = ManualItem(
        assurance="manual-artefact",
        outcome=None,
        reviewer="A. Reviewer",
        reviewed_on=AS_OF.date(),
        sha256="a" * 64,
        components={"plan": True, "exercise": False},
    )
    evidence = Evidence(as_of=AS_OF, manual={control.id: manual})
    result = evaluate_control(LIBRARY, control, evidence)
    assert (result.status, result.quality) == ("partial", Decimal("0.9"))
    assert contribution(control, result) == Fraction(9, 10)
    inputs = control_inputs(LIBRARY, evaluate_all(LIBRARY, evidence))
    [scored] = [
        score_control(item, AS_OF) for item in inputs if item.control_id == control.id
    ]
    assert scored.contribution == Fraction(9, 10)


# --- edge vector v: coverage below 0.60 ---------------------------------------------


def custom(
    statuses: list[tuple[str, int]],
) -> tuple[list[ControlInput], list[DomainWeight]]:
    """Controls of one domain X given as (status, weight); fresh if they have any."""
    controls = [
        ControlInput(
            f"PC-X-{number:02d}",
            "X",
            weight,
            False,
            status,  # type: ignore[arg-type]
            Fraction(0 if status in ("unknown", "na") else 1),
            None if status in ("unknown", "na") else AS_OF,
            35,
        )
        for number, (status, weight) in enumerate(statuses, start=1)
    ]
    return controls, [DomainWeight("X", 100)]


def test_coverage_below_sixty_percent_prints_a_lower_bound_only() -> None:
    controls, domains = custom([("pass", 2), ("unknown", 3)])
    result = score_inputs(controls, domains, AS_OF)
    assert result.coverage == Fraction(2, 5) and result.insufficient
    assert result.band == "Insufficient evidence"
    assert result.best_case is None, "no best case beside a lower bound"
    assert result.upper == 100
    assert headline(result) == (
        "Insufficient evidence: lower bound 40.0, evidence coverage 40 percent"
    )


def test_coverage_of_exactly_sixty_percent_is_enough() -> None:
    controls, domains = custom([("pass", 3), ("unknown", 2)])
    result = score_inputs(controls, domains, AS_OF)
    assert result.coverage == Fraction(3, 5)
    assert not result.insufficient
    assert result.band == "Fair"
    assert result.best_case == 100


# --- edge vector vi: not-applicable weight above 20 percent -------------------------


def test_not_applicable_weight_above_twenty_percent_raises_a_visible_flag() -> None:
    controls, domains = custom([("na", 1), ("pass", 1), ("pass", 1), ("pass", 2)])
    assert not score_inputs(controls, domains, AS_OF).na_flagged, "exactly 20 percent"
    controls, domains = custom([("na", 2), ("pass", 1), ("pass", 1), ("pass", 2)])
    result = score_inputs(controls, domains, AS_OF)
    assert result.na_flagged and result.na_weight == 2


# --- edge vector vii: empty populations ---------------------------------------------


def entra(*users: dict[str, Any]) -> dict[str, Any]:
    return {"sources": {"entra-registration": {"kinds": {"user": list(users)}}}}


MEMBER = {"user_type": "member", "mfa_registered": True, "mfa_capable": True}


def test_a_share_rule_with_an_empty_denominator_is_unknown() -> None:
    control = LIBRARY.control("PC-ACC-01")
    result = evaluate_control(LIBRARY, control, build_evidence(entra()))
    assert (result.status, result.reason) == ("unknown", "empty_population")


def test_a_none_wanted_count_rule_with_an_empty_population_passes() -> None:
    control = LIBRARY.control("PC-ACC-02")
    users = [{**MEMBER, "user": "u1", "is_admin": False}]
    result = evaluate_control(LIBRARY, control, build_evidence(entra(*users)))
    assert result.status == "pass"
    assert (result.numerator, result.denominator) == (0, 0)
