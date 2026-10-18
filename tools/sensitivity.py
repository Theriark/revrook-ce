"""The sensitivity harness of the control weights (phase 5, part 2).

    python3 tools/sensitivity.py [REPORT_FILE]

Weights are our own uncalibrated design choices (rnd-report-3 sections 3.4 and 3.5),
so the harness asks two questions of them and records the answers, whatever they are:

1. Do the published weights (3, 2 or 1 per control, the domain weights) rank a set of
   clients differently from equal weights (every control 1, every domain equal)? The
   answer is the Spearman rank correlation of the two scores.
2. Do 200 random perturbations of every control weight by one tier (1 to 2, 3 to 2,
   2 to 1 or 3) change that ranking? The answer is the Spearman correlation of each
   perturbed score with the published one.

The pre-registered thresholds are 0.90 for both. A result below them is a negative
result to record in docs/scoring.md, never a reason to tune a weight.

The clients are synthetic: 12 sets of evidence drawn from a fixed seed. Each control
takes the evidence of one stored vector (tests/vectors) whose result is pass, partial,
fail or unknown, so every result comes from the real check engine; a manual-only
control takes a manual artefact (quality 0.9) or an attestation (0.6). Each client has
its own overall level and its own level per domain, so that the weights have
something to disagree about. The score here is the raw one of rnd-report-3 section
3.5 (weight x r x q, no freshness, no gate cap): freshness and gates belong to the
scoring engine of phase 6. Twelve synthetic clients are a check that the harness and
the arithmetic work, not evidence that the weights are right.
"""

import json
import random
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.checks.engine import control_score, evaluate_control
from app.checks.library import Control, Library, load_library
from app.checks.model import Evidence, ManualItem
from tools.vector_facts import AS_OF, build_evidence

ROOT = Path(__file__).resolve().parent.parent
VECTOR_DIR = ROOT / "tests" / "vectors"
DEFAULT_REPORT = ROOT / "build" / "sensitivity-report.json"
SEED = 20261018
CLIENTS = 12
PERTURBATIONS = 200
THRESHOLD = 0.90
TIERS = (1, 2, 3)
REVIEWED_ON = date(2026, 10, 1)
ARTEFACT_SHA = "0" * 64


def rank(values: Sequence[Fraction]) -> list[Fraction]:
    """Ranks from 1, tied values sharing the average of their positions."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [Fraction(0)] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        average = Fraction(start + end, 2) + 1
        for position in range(start, end + 1):
            ranks[order[position]] = average
        start = end + 1
    return ranks


def spearman(first: Sequence[Fraction], second: Sequence[Fraction]) -> float | None:
    """The Spearman rank correlation (Pearson on the ranks); None when one side has
    no spread, because the correlation is then undefined.
    """
    if len(first) != len(second) or len(first) < 2:
        raise ValueError("two series of the same length, at least two values")
    left, right = rank(first), rank(second)
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    spread_left = sum((a - mean_left) ** 2 for a in left)
    spread_right = sum((b - mean_right) ** 2 for b in right)
    if spread_left == 0 or spread_right == 0:
        return None
    return float(covariance) / float(spread_left * spread_right) ** 0.5


def load_pool() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """The stored vectors, by control and expected status."""
    pool: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for path in sorted(VECTOR_DIR.glob("*.json")):
        content = json.loads(path.read_text(encoding="utf-8"))
        by_status: dict[str, list[dict[str, Any]]] = {}
        for vector in content["vectors"]:
            by_status.setdefault(vector["expect"]["status"], []).append(vector)
        pool[content["control"]] = by_status
    return pool


def draw_status(level: float, generator: random.Random) -> str:
    """pass, partial, fail or unknown: the better the level the more passes."""
    chance = generator.random()
    if chance < level:
        return "pass"
    rest = (chance - level) / (1 - level) if level < 1 else 1.0
    if rest < 0.35:
        return "partial"
    return "unknown" if rest > 0.85 else "fail"


def result_fraction(
    library: Library,
    control: Control,
    status: str,
    pool: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    generator: random.Random,
) -> Fraction:
    """r x q of the control for a drawn status, from the real engine."""
    if control.manual_only:
        if status in ("unknown", "fail"):
            return Fraction(0)
        artefact = generator.random() < 0.5
        item = ManualItem(
            assurance="manual-artefact" if artefact else "attestation",
            outcome="pass" if status == "pass" else "partial",
            reviewer="A. Reviewer",
            reviewed_on=REVIEWED_ON,
            sha256=ARTEFACT_SHA if artefact else None,
        )
        evidence = Evidence(as_of=AS_OF, manual={control.id: item})
        return control_score(evaluate_control(library, control, evidence))
    found = pool[control.id]
    options = found.get(status) or found.get("unknown") or []
    vector = options[generator.randrange(len(options))]
    evidence = build_evidence(vector["evidence"])
    return control_score(evaluate_control(library, control, evidence))


def synthetic_clients(
    library: Library, pool: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]
) -> list[dict[str, Fraction]]:
    """For each client, r x q of every control, by control id."""
    generator = random.Random(SEED)
    clients: list[dict[str, Fraction]] = []
    for index in range(CLIENTS):
        overall = 0.15 + 0.75 * index / (CLIENTS - 1)
        levels = {
            domain.code: min(0.97, max(0.03, overall + generator.uniform(-0.25, 0.25)))
            for domain in library.domains
        }
        row: dict[str, Fraction] = {}
        for control in library.controls:
            status = draw_status(levels[control.domain], generator)
            row[control.id] = result_fraction(library, control, status, pool, generator)
        clients.append(row)
    return clients


def overall_score(
    library: Library,
    results: Mapping[str, Fraction],
    control_weights: Mapping[str, int],
    domain_weights: Mapping[str, int],
) -> Fraction:
    """O of rnd-report-3 section 3.5 for r x q results and the given weights."""
    total = Fraction(0)
    domain_total = 0
    for domain in library.domains:
        controls = [item for item in library.controls if item.domain == domain.code]
        weight_sum = sum(control_weights[item.id] for item in controls)
        earned = sum(control_weights[item.id] * results[item.id] for item in controls)
        total += domain_weights[domain.code] * 100 * earned / weight_sum
        domain_total += domain_weights[domain.code]
    return total / domain_total


def perturbed_weights(
    weights: Mapping[str, int], generator: random.Random
) -> dict[str, int]:
    """Every control weight moved one tier: 1 to 2, 3 to 2, 2 to 1 or 3."""
    changed: dict[str, int] = {}
    for control_id, weight in weights.items():
        neighbours = [tier for tier in TIERS if abs(tier - weight) == 1]
        changed[control_id] = neighbours[generator.randrange(len(neighbours))]
    return changed


def run(library: Library | None = None) -> dict[str, Any]:
    """The whole experiment; the report is plain data and the same on every run."""
    library = library or load_library()
    clients = synthetic_clients(library, load_pool())
    published = {item.id: item.weight for item in library.controls}
    domains = {item.code: item.weight for item in library.domains}
    equal_controls = {item.id: 1 for item in library.controls}
    equal_domains = {item.code: 1 for item in library.domains}
    base = [overall_score(library, row, published, domains) for row in clients]
    equal = [
        overall_score(library, row, equal_controls, equal_domains) for row in clients
    ]
    generator = random.Random(SEED + 1)
    correlations: list[float | None] = []
    for _ in range(PERTURBATIONS):
        weights = perturbed_weights(published, generator)
        moved = [overall_score(library, row, weights, domains) for row in clients]
        correlations.append(spearman(base, moved))
    defined = [value for value in correlations if value is not None]
    equal_correlation = spearman(base, equal)
    lowest = min(defined) if defined else None
    return {
        "ruleset": f"{library.ruleset_id} v{library.version}",
        "seed": SEED,
        "clients": CLIENTS,
        "scores_published": [round(float(value), 2) for value in base],
        "scores_equal_weights": [round(float(value), 2) for value in equal],
        "spearman_equal_weights": _round(equal_correlation),
        "perturbations": PERTURBATIONS,
        "perturbation_spearman_min": _round(lowest),
        "perturbation_spearman_mean": _round(_mean(defined)),
        "perturbation_share_at_least_threshold": _round(_share_meeting(defined)),
        "threshold": THRESHOLD,
        "equal_weights_meets_threshold": _meets(equal_correlation),
        "perturbations_meet_threshold": _meets(lowest),
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _share_meeting(values: Sequence[float]) -> float | None:
    """The share of the correlations that reach the pre-registered threshold."""
    if not values:
        return None
    return sum(1 for value in values if value >= THRESHOLD) / len(values)


def _meets(value: float | None) -> bool:
    return value is not None and value >= THRESHOLD


def summary(report: Mapping[str, Any]) -> str:
    """The lines CI prints."""
    return "\n".join(
        [
            f"sensitivity harness {report['ruleset']}: {report['clients']} synthetic "
            f"clients, seed {report['seed']}",
            f"Spearman, published weights against equal weights: "
            f"{report['spearman_equal_weights']} "
            f"(threshold {report['threshold']}, "
            f"{'met' if report['equal_weights_meets_threshold'] else 'NOT met'})",
            f"Spearman over {report['perturbations']} one-tier perturbations: "
            f"min {report['perturbation_spearman_min']}, "
            f"mean {report['perturbation_spearman_mean']}, "
            f"{report['perturbation_share_at_least_threshold']} of them at least "
            f"{report['threshold']}",
        ]
    )


def write_report(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    path = Path(arguments[0]) if arguments else DEFAULT_REPORT
    report = run()
    write_report(report, path)
    print(summary(report))
    print(f"report written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
