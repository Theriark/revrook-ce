"""The six properties of rnd-report-3 section 3.5, over 600 random cases each.

hypothesis is not in the development lock (requirements-dev.txt), and the lock may
not be changed by hand, so the cases are drawn with random.Random and a fixed seed:
the same 600 cases on every run, and a failing case can be replayed from its seed.
A case is a random state of all 51 controls (status, quality, evidence age, not
applicable); the properties are checked on the exact scores, with no tolerance.
"""

import random
from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction
from typing import Any

from app.checks.library import load_library
from app.checks.model import Evidence, ManualItem
from app.scoring.engine import (
    domain_weights,
    freshness,
    score_control,
    score_evidence,
    score_inputs,
)
from app.scoring.model import ControlInput, DomainWeight
from tools.score_inputs import AS_OF

LIBRARY = load_library()
DOMAINS = domain_weights(LIBRARY)
CASES = 600
SEED = 20261018
STATUSES = ["pass", "partial", "fail", "unknown", "na"]
# How often a state draws each status: pass varies per state (weak to strong
# clients), then partial, fail, unknown and not applicable.
PASS_WEIGHTS = [20, 50, 80, 150]
STATUS_WEIGHTS = [10, 8, 10, 4]
QUALITIES = [Fraction(1), Fraction(9, 10), Fraction(3, 5)]
HOUR = timedelta(hours=1)
MICROSECOND = timedelta(microseconds=1)
NINE_TENTHS = Fraction(9, 10)


def limit_of(control_id: str) -> int:
    ages = LIBRARY.control(control_id).max_age_days
    return ages.automatic or ages.manual or 35


def random_age(rng: random.Random, limit: int) -> timedelta:
    """From 0 to M (three times in five) or to 3 M, in whole hours (so that an age
    of exactly M or 2 M can occur).
    """
    top = limit if rng.random() < 0.6 else 3 * limit
    return rng.randrange(0, 24 * top + 1) * HOUR


def random_evidence(
    item: ControlInput, rng: random.Random, status: str | None = None
) -> ControlInput:
    """The control with new evidence: a status, a quality and an age."""
    chosen: Any = status or rng.choice(["pass", "partial", "fail"])
    limit = item.max_age_days or 35
    return replace(
        item,
        status=chosen,
        quality=rng.choice(QUALITIES),
        evidence_at=AS_OF - random_age(rng, limit),
    )


def random_state(rng: random.Random) -> list[ControlInput]:
    """A random state of every control of the library."""
    found: list[ControlInput] = []
    weights = [rng.choice(PASS_WEIGHTS), *STATUS_WEIGHTS]
    for control in LIBRARY.controls:
        status: Any = rng.choices(STATUSES, weights=weights)[0]
        limit = None if rng.random() < 0.1 else limit_of(control.id)
        base = ControlInput(
            control.id,
            control.domain,
            control.weight,
            control.gate,
            status,
            Fraction(0),
            None,
            limit,
        )
        if status in ("unknown", "na"):
            found.append(base)
        elif rng.random() < 0.1:
            found.append(replace(base, quality=rng.choice(QUALITIES)))
        else:
            found.append(random_evidence(base, rng, status))
    return found


def blank(item: ControlInput) -> ControlInput:
    """The control with its evidence removed: unknown, quality 0, no time."""
    return replace(item, status="unknown", quality=Fraction(0), evidence_at=None)


def remove_a_fifth(items: list[ControlInput], rng: random.Random) -> list[ControlInput]:
    """The same state with a random 20 percent of its applicable controls blanked."""
    counted = [n for n, item in enumerate(items) if item.status != "na"]
    removed = set(rng.sample(counted, max(1, len(counted) // 5)))
    return [blank(item) if n in removed else item for n, item in enumerate(items)]


def age_of(item: ControlInput) -> timedelta | None:
    if item.evidence_at is None:
        return None
    return max(AS_OF - item.evidence_at, timedelta(0))


def is_stale(item: ControlInput) -> bool:
    age = age_of(item)
    if age is None or item.max_age_days is None:
        return False
    return age > timedelta(days=item.max_age_days)


def test_there_are_at_least_500_cases_per_property() -> None:
    assert CASES >= 500


# --- property 1: adding or refreshing evidence never lowers a score -----------------


def improve(item: ControlInput, rng: random.Random) -> ControlInput:
    """Add evidence where there is none; refresh (a later time) where there is."""
    if item.status == "na":
        return item
    if item.status == "unknown":
        return random_evidence(item, rng) if rng.random() < 0.5 else item
    age = age_of(item)
    if age is None:
        return item
    return replace(item, evidence_at=AS_OF - age * rng.randrange(0, 101) // 100)


def test_adding_or_refreshing_evidence_never_lowers_a_score() -> None:
    rng = random.Random(SEED + 1)
    for _ in range(CASES):
        before = random_state(rng)
        after = [improve(item, rng) for item in before]
        old = score_inputs(before, DOMAINS, AS_OF)
        new = score_inputs(after, DOMAINS, AS_OF)
        for first, second in zip(old.controls, new.controls, strict=True):
            assert second.score >= first.score, first.control_id
        assert new.score >= old.score


# --- property 2: unknown scores 0 and stays in the denominator ----------------------


def test_unknown_scores_zero_and_removing_evidence_never_raises_the_score() -> None:
    rng = random.Random(SEED + 2)
    for _ in range(CASES):
        full = random_state(rng)
        before = score_inputs(full, DOMAINS, AS_OF)
        after = score_inputs(remove_a_fifth(full, rng), DOMAINS, AS_OF)
        assert after.score <= before.score
        for scored in after.controls:
            if scored.status == "unknown":
                assert scored.score == 0 and scored.contribution == 0
        for first, second in zip(before.domains, after.domains, strict=True):
            assert second.possible == first.possible, "the denominator stays"


def test_only_a_reviewer_decision_can_raise_the_score_by_removing_a_control() -> None:
    failed = ControlInput("PC-X-01", "X", 2, False, "fail", Fraction(1), AS_OF, 7)
    passed = replace(failed, control_id="PC-X-02", status="pass")
    domain = [DomainWeight("X", 100)]
    assert score_inputs([failed, passed], domain, AS_OF).score == 50
    not_applicable = replace(failed, status="na", quality=Fraction(0))
    assert score_inputs([not_applicable, passed], domain, AS_OF).score == 100


# --- property 3: stale decays to zero by 2 M ----------------------------------------


def test_stale_evidence_decays_in_a_straight_line_to_zero_by_two_m() -> None:
    rng = random.Random(SEED + 3)
    for _ in range(CASES):
        limit = rng.randrange(1, 401)
        unit = timedelta(days=limit)
        first = random_age(rng, limit)
        second = first + rng.randrange(0, 24 * limit + 1) * HOUR
        early, late = freshness(first, limit), freshness(second, limit)
        assert 0 <= late <= early <= 1
        if first <= unit:
            assert early == 1
        if first >= 2 * unit:
            assert early == 0
        if unit < first < 2 * unit:
            period = Fraction(unit // MICROSECOND)
            over = Fraction(first // MICROSECOND) - period
            assert early == 1 - over / period
        item = ControlInput("PC-X-01", "X", 3, False, "pass", Fraction(1), None, limit)
        scored = score_control(replace(item, evidence_at=AS_OF - second), AS_OF)
        assert scored.contribution == 3 * late
        assert scored.stale is (second > unit)
        if second >= 2 * unit:
            assert scored.contribution == 0


# --- property 4: manual-only controls reach at most 0.9 of their weight -------------


def random_manual(rng: random.Random, control_id: str) -> ManualItem:
    components = {}
    if control_id == "PC-GOV-05":
        components = {"plan": rng.random() < 0.7, "exercise": rng.random() < 0.7}
    assurance: Any = rng.choice(["manual-artefact", "attestation"])
    outcome: Any = rng.choice(["pass", "partial", "fail", None])
    return ManualItem(
        assurance=assurance,
        outcome=outcome,
        reviewer=rng.choice(["A. Reviewer", "", "B. Reviewer"]),
        reviewed_on=date(2026, 10, 17) - timedelta(days=rng.randrange(0, 500)),
        sha256=rng.choice([None, "a" * 64]),
        components=components,
    )


def test_manual_only_controls_reach_at_most_nine_tenths_of_their_weight() -> None:
    rng = random.Random(SEED + 4)
    for _ in range(CASES):
        control = rng.choice(LIBRARY.manual_only)
        manual = {control.id: random_manual(rng, control.id)}
        result = score_evidence(LIBRARY, Evidence(as_of=AS_OF, manual=manual))
        [scored] = [item for item in result.controls if item.control_id == control.id]
        assert scored.quality <= NINE_TENTHS
        assert scored.contribution <= NINE_TENTHS * control.weight


# --- property 5: gates cap the headline ---------------------------------------------


def expected_cap(items: list[ControlInput]) -> int | None:
    """The cap of rnd-report-3 section 3.5, written again from the text."""
    caps: list[int] = []
    for item in items:
        if not item.gate or item.status == "na":
            continue
        expired = is_stale(item) and freshness(age_of(item), item.max_age_days) == 0
        if item.status in ("fail", "unknown") or expired:
            caps.append(49)
        elif item.status == "partial" or is_stale(item):
            caps.append(69)
    return min(caps) if caps else None


def test_gates_cap_the_headline_score() -> None:
    rng = random.Random(SEED + 5)
    capped = 0
    for _ in range(CASES):
        items = random_state(rng)
        result = score_inputs(items, DOMAINS, AS_OF)
        cap = expected_cap(items)
        assert result.score <= result.raw
        if cap is None:
            assert result.cap is None and result.score == result.raw
            continue
        assert result.cap is not None and result.cap.limit == cap
        assert result.score == min(result.raw, cap)
        capped += result.capped
    assert capped > 50, "the random cases must reach the caps"


# --- property 6: S is a lower bound and U an upper bound of completions -------------


def complete(item: ControlInput, rng: random.Random) -> ControlInput:
    """Fill in what is missing: new evidence for unknown, a fresh export for stale."""
    if item.status == "na":
        return item
    if item.status == "unknown":
        return replace(random_evidence(item, rng), evidence_at=AS_OF)
    if is_stale(item):
        return replace(item, evidence_at=AS_OF)
    return item


def test_the_score_is_a_lower_bound_and_the_best_case_an_upper_bound() -> None:
    rng = random.Random(SEED + 6)
    for _ in range(CASES):
        items = random_state(rng)
        result = score_inputs(items, DOMAINS, AS_OF)
        assert result.score <= result.upper <= 100
        for _ in range(3):
            filled = [complete(item, rng) for item in items]
            score = score_inputs(filled, DOMAINS, AS_OF).score
            assert result.score <= score <= result.upper


def test_the_lower_bound_never_exceeds_the_score_with_full_evidence() -> None:
    """Deleting a random 20 percent of the evidence never raises S."""
    rng = random.Random(SEED + 7)
    for _ in range(CASES):
        full = random_state(rng)
        lower = score_inputs(remove_a_fifth(full, rng), DOMAINS, AS_OF)
        whole = score_inputs(full, DOMAINS, AS_OF)
        assert lower.score <= whole.score
        assert whole.score <= lower.upper
