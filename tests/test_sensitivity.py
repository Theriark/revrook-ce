"""The sensitivity harness of the control weights (phase 5, part 2).

The harness runs here, inside the normal test run, writes its report to
build/sensitivity-report.json and prints the Spearman correlation with equal weights
(tests/conftest.py prints the summary at the end of the run). The result may be below
the pre-registered 0.90: the test then still passes, and docs/scoring.md must record
the number. A weight is never tuned to reach the threshold.
"""

import functools
import json
import random
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from app.checks.library import load_library
from tools import sensitivity

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = sensitivity.DEFAULT_REPORT
SCORING_DOC = ROOT / "docs" / "scoring.md"
LIBRARY = load_library()


@functools.cache
def harness_report() -> dict[str, Any]:
    """The experiment, run once for the whole module; its report is written and its
    summary printed here (tests/conftest.py prints it again at the end of the run).
    """
    result = sensitivity.run(LIBRARY)
    sensitivity.write_report(result, REPORT_PATH)
    print(sensitivity.summary(result))
    return result


def fractions(*values: int) -> list[Fraction]:
    return [Fraction(value) for value in values]


def test_spearman_of_the_same_order_is_one_and_of_the_reverse_is_minus_one() -> None:
    assert sensitivity.spearman(fractions(1, 2, 3, 4), fractions(10, 20, 30, 40)) == 1
    assert sensitivity.spearman(fractions(1, 2, 3, 4), fractions(4, 3, 2, 1)) == -1


def test_ties_share_the_average_rank() -> None:
    assert sensitivity.rank(fractions(5, 5, 9, 1)) == [
        Fraction(5, 2),
        Fraction(5, 2),
        Fraction(4),
        Fraction(1),
    ]
    # A hand-worked case: ranks (1.5, 1.5, 3, 4) and (1, 2, 3, 4).
    value = sensitivity.spearman(fractions(7, 7, 8, 9), fractions(1, 2, 3, 4))
    assert value is not None
    assert abs(value - 0.9486833) < 1e-6


def test_a_series_without_spread_has_no_correlation() -> None:
    assert sensitivity.spearman(fractions(3, 3, 3), fractions(1, 2, 3)) is None


def test_spearman_needs_two_series_of_the_same_length() -> None:
    with pytest.raises(ValueError):
        sensitivity.spearman(fractions(1, 2), fractions(1, 2, 3))
    with pytest.raises(ValueError):
        sensitivity.spearman(fractions(1), fractions(1))


def test_every_perturbed_weight_moves_exactly_one_tier() -> None:
    weights = {control.id: control.weight for control in LIBRARY.controls}
    generator = random.Random(1)
    for _ in range(20):
        moved = sensitivity.perturbed_weights(weights, generator)
        assert set(moved) == set(weights)
        for control_id, weight in weights.items():
            assert abs(moved[control_id] - weight) == 1
            assert moved[control_id] in sensitivity.TIERS


def test_equal_results_score_the_same_whatever_the_weights() -> None:
    domains = {item.code: item.weight for item in LIBRARY.domains}
    half = {control.id: Fraction(1, 2) for control in LIBRARY.controls}
    weights = {control.id: control.weight for control in LIBRARY.controls}
    score = sensitivity.overall_score(LIBRARY, half, weights, domains)
    assert score == 50
    ones = {control.id: 1 for control in LIBRARY.controls}
    assert sensitivity.overall_score(LIBRARY, half, ones, domains) == 50


def test_the_report_is_complete_and_the_same_on_every_run() -> None:
    report = harness_report()
    assert report == sensitivity.run(LIBRARY)
    assert report["clients"] == 12
    assert report["perturbations"] == 200
    assert report["threshold"] == 0.90
    for key in (
        "spearman_equal_weights",
        "perturbation_spearman_min",
        "perturbation_spearman_mean",
    ):
        value = report[key]
        assert isinstance(value, float)
        assert -1 <= value <= 1, key
    assert len(report["scores_published"]) == 12
    assert len(set(report["scores_published"])) > 1


def test_the_report_file_is_written() -> None:
    report = harness_report()
    assert json.loads(REPORT_PATH.read_text(encoding="utf-8")) == report


def test_the_summary_names_the_correlation_with_equal_weights() -> None:
    report = harness_report()
    text = sensitivity.summary(report)
    assert "Spearman, published weights against equal weights" in text
    assert str(report["spearman_equal_weights"]) in text


def test_the_result_is_recorded_in_the_scoring_document() -> None:
    """Whatever the numbers are, docs/scoring.md must state them (a negative result
    included) so that nobody has to run the harness to learn them.
    """
    report = harness_report()
    text = SCORING_DOC.read_text(encoding="utf-8")
    for key in (
        "spearman_equal_weights",
        "perturbation_spearman_min",
        "perturbation_spearman_mean",
    ):
        assert f"{report[key]:.3f}" in text, f"docs/scoring.md must record {key}"
    lowered = text.lower()
    verdict = "met" if report["equal_weights_meets_threshold"] else "not met"
    assert f"threshold against equal weights: {verdict}" in lowered
    verdict = "met" if report["perturbations_meet_threshold"] else "not met"
    assert f"threshold under perturbation: {verdict}" in lowered
