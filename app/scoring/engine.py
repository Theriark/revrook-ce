"""The scoring engine: exact, reproducible and never flattering (phase 6).

Pure functions over what the check engine decided. They read no clock, database or
network, and use no float: every value is a `Fraction`. The model is section 3.5 of
rnd-report-3.

* Control score s = r x q x f. r is 1 for a pass, a fixed one half for a partial and
  0 for a fail, unknown or not-applicable control; q is the evidence quality; f is
  the freshness: 1 up to the maximum age M, falling in a straight line to 0 at 2M.
* Domain score D = 100 x (sum of weight x s) / Wa, Wa being the weight of the controls
  that are not not-applicable; unknown and stale controls stay in Wa. Overall O is the
  domain-weighted mean of D over the domains that are not dropped (all controls not
  applicable).
* Gates: a gate control that fails, is unknown or has expired evidence (f = 0) caps
  the score at 49; a gate control that is partial or stale (f above 0) caps it at 69.
  S = min(O, cap) and the cap is kept beside the raw score.
* Coverage is the weight of controls with fresh pass, partial or fail evidence over
  the weight of controls that are not not-applicable. The best case U is the score
  with every unknown and stale control set to pass at quality 1 and freshness 1,
  capped by the gate rule on that state; a fail or partial that is fresh is not
  improved. Below the coverage minimum the band is Insufficient evidence and the
  number is a lower bound only.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from fractions import Fraction

from app.checks.engine import STATUS_VALUE, evaluate_all
from app.checks.library import Library
from app.checks.model import ControlResult, Evidence
from app.scoring.model import (
    DEFAULT_THRESHOLDS,
    GATE_EXPIRED,
    GATE_FAIL,
    GATE_PARTIAL,
    GATE_STALE,
    GATE_UNKNOWN,
    ControlInput,
    ControlScore,
    DomainScore,
    DomainWeight,
    GateCap,
    ScoreResult,
    Thresholds,
)

MICROSECOND = timedelta(microseconds=1)
HUNDRED = Fraction(100)
ZERO = Fraction(0)
ONE = Fraction(1)
COVERED_STATUSES = frozenset({"pass", "partial", "fail"})
# A maximum age beyond one hundred years is a mistake, not a policy; it also keeps
# every date calculation far from the limits of a timedelta.
MAX_AGE_DAYS = 36500


def require_aware(value: datetime, name: str) -> datetime:
    """The datetime itself, or a ValueError when it carries no timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must carry a timezone (use UTC), not be naive")
    return value


def age_of(evidence_at: datetime | None, as_of: datetime) -> timedelta | None:
    """The age of evidence at the pack date (never negative); None without a time."""
    if evidence_at is None:
        return None
    require_aware(evidence_at, "the evidence time")
    return max(as_of - evidence_at, timedelta(0))


def is_stale(age: timedelta | None, max_age_days: int | None) -> bool:
    """Whether the evidence is older than the maximum age M."""
    if age is None or max_age_days is None:
        return False
    return age > timedelta(days=max_age_days)


def freshness(age: timedelta | None, max_age_days: int | None) -> Fraction:
    """f: 1 when the age is at most M, 1 - (A - M) / M up to 2M, 0 from 2M on."""
    if age is None or max_age_days is None:
        return ONE
    limit = timedelta(days=max_age_days)
    if age <= limit:
        return ONE
    if age >= 2 * limit:
        return ZERO
    return 2 - Fraction(age // MICROSECOND, limit // MICROSECOND)


def score_control(item: ControlInput, as_of: datetime) -> ControlScore:
    """s = r x q x f of one control, and the weight it earned."""
    age = age_of(item.evidence_at, as_of)
    fresh = freshness(age, item.max_age_days)
    stale = is_stale(age, item.max_age_days)
    score = STATUS_VALUE[item.status] * item.quality * fresh
    return ControlScore(
        control_id=item.control_id,
        domain=item.domain,
        weight=item.weight,
        gate=item.gate,
        status=item.status,
        quality=item.quality,
        freshness=fresh,
        stale=stale,
        counted=item.status != "na",
        covered=item.status in COVERED_STATUSES and not stale,
        score=score,
        contribution=item.weight * score,
    )


def score_domain(domain: DomainWeight, controls: Sequence[ControlScore]) -> DomainScore:
    """D of one domain; None when every control of it is not applicable."""
    members = [item for item in controls if item.domain == domain.code]
    possible = sum(item.weight for item in members if item.counted)
    earned = sum((item.contribution for item in members), ZERO)
    score = HUNDRED * earned / possible if possible else None
    return DomainScore(domain.code, domain.weight, earned, possible, score)


def overall(domains: Sequence[DomainScore]) -> Fraction:
    """O: the domain-weighted mean of D over the domains that are not dropped."""
    weight = 0
    total = ZERO
    for domain in domains:
        if domain.score is not None:
            weight += domain.weight
            total += domain.weight * domain.score
    return total / weight if weight else ZERO


def _gate_cap(item: ControlScore, thresholds: Thresholds) -> GateCap | None:
    """The cap one gate control puts on the score, if any."""
    if item.status in ("fail", "unknown"):
        reason = GATE_FAIL if item.status == "fail" else GATE_UNKNOWN
        return GateCap(item.control_id, thresholds.cap_fail, reason)
    if item.stale and item.freshness == 0:
        return GateCap(item.control_id, thresholds.cap_fail, GATE_EXPIRED)
    if item.status == "partial":
        return GateCap(item.control_id, thresholds.cap_partial, GATE_PARTIAL)
    if item.stale:
        return GateCap(item.control_id, thresholds.cap_partial, GATE_STALE)
    return None


def gate_cap(
    controls: Sequence[ControlScore], thresholds: Thresholds
) -> GateCap | None:
    """The lowest cap of the gate controls (the first one when two are equal)."""
    chosen: GateCap | None = None
    for item in controls:
        if not item.gate or not item.counted:
            continue
        found = _gate_cap(item, thresholds)
        if found is not None and (chosen is None or found.limit < chosen.limit):
            chosen = found
    return chosen


def band_of(score: Fraction, thresholds: Thresholds) -> str:
    """The band of an exact score (not of its rounded display)."""
    for name, lowest in thresholds.bands:
        if score >= lowest:
            return name
    return thresholds.lowest_band


def check_inputs(
    inputs: Sequence[ControlInput], domains: Sequence[DomainWeight]
) -> None:
    """Raise ValueError for inputs the engine cannot score faithfully.

    A maximum age is checked here, before any date arithmetic: a negative one has no
    meaning, and one beyond `MAX_AGE_DAYS` would overflow a timedelta (OverflowError)
    on the way to a score.
    """
    codes = [item.code for item in domains]
    if len(set(codes)) != len(codes):
        raise ValueError("a domain is listed twice")
    ids = [item.control_id for item in inputs]
    if len(set(ids)) != len(ids):
        raise ValueError("a control is listed twice")
    for item in inputs:
        if item.domain not in codes:
            raise ValueError(f"{item.control_id}: there is no domain {item.domain}")
        if item.weight < 0 or not 0 <= item.quality <= 1:
            raise ValueError(f"{item.control_id}: weight or quality out of range")
        limit = item.max_age_days
        if limit is not None and not 0 <= limit <= MAX_AGE_DAYS:
            raise ValueError(
                f"{item.control_id}: max_age_days must be 0 to {MAX_AGE_DAYS}"
            )
    if any(item.weight < 0 for item in domains):
        raise ValueError("a domain weight is negative")


@dataclass(frozen=True)
class _Assessment:
    """The scored controls and domains, O and the gate cap of one state."""

    controls: tuple[ControlScore, ...]
    domains: tuple[DomainScore, ...]
    raw: Fraction
    cap: GateCap | None

    @property
    def score(self) -> Fraction:
        """S = min(O, cap)."""
        cap = self.cap
        return self.raw if cap is None else min(self.raw, Fraction(cap.limit))


def _assess(
    inputs: Sequence[ControlInput],
    domains: Sequence[DomainWeight],
    as_of: datetime,
    thresholds: Thresholds,
) -> _Assessment:
    controls = tuple(score_control(item, as_of) for item in inputs)
    scored = tuple(score_domain(domain, controls) for domain in domains)
    cap = gate_cap(controls, thresholds)
    return _Assessment(controls, scored, overall(scored), cap)


def _completed(item: ControlInput, as_of: datetime) -> ControlInput:
    """The control as it would be with fresh evidence that passes (best case).

    Unknown and stale controls become a pass at quality 1 and freshness 1; every
    other control, not-applicable ones included, stays as it is.
    """
    stale = score_control(item, as_of).stale
    if item.status == "na" or not (item.status == "unknown" or stale):
        return item
    return replace(item, status="pass", quality=ONE, evidence_at=as_of)


def score_inputs(
    inputs: Sequence[ControlInput],
    domains: Sequence[DomainWeight],
    as_of: datetime,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> ScoreResult:
    """The score of one client from the inputs of its controls.

    Raises ValueError for a naive `as_of` or evidence time, a control with an
    unknown domain, or a duplicate: a control can never be left out silently.
    """
    require_aware(as_of, "as_of")
    check_inputs(inputs, domains)
    state = _assess(inputs, domains, as_of, thresholds)
    completed = [_completed(item, as_of) for item in inputs]
    best = _assess(completed, domains, as_of, thresholds)
    counted = sum(item.weight for item in state.controls if item.counted)
    covered = sum(item.weight for item in state.controls if item.covered)
    coverage = Fraction(covered, counted) if counted else ZERO
    total = sum(item.weight for item in state.controls)
    na_weight = total - counted
    insufficient = coverage < thresholds.min_coverage
    band = thresholds.insufficient_band
    if not insufficient:
        band = band_of(state.score, thresholds)
    flagged = total > 0 and Fraction(na_weight, total) > thresholds.na_flag_above
    return ScoreResult(
        as_of=as_of,
        controls=state.controls,
        domains=state.domains,
        raw=state.raw,
        cap=state.cap,
        score=state.score,
        coverage=coverage,
        upper=best.score,
        band=band,
        insufficient=insufficient,
        na_weight=na_weight,
        na_flagged=flagged,
        dropped_domains=tuple(
            item.code for item in state.domains if item.score is None
        ),
    )


def domain_weights(library: Library) -> tuple[DomainWeight, ...]:
    return tuple(DomainWeight(item.code, item.weight) for item in library.domains)


def control_inputs(
    library: Library, results: Mapping[str, ControlResult]
) -> tuple[ControlInput, ...]:
    """The scoring inputs of every control of the library, in file order.

    A control without a result is an error, not a zero: it would be left out of the
    score without a word.
    """
    found: list[ControlInput] = []
    for control in library.controls:
        result = results.get(control.id)
        if result is None:
            raise ValueError(f"{control.id}: the control has no result")
        found.append(
            ControlInput(
                control_id=control.id,
                domain=control.domain,
                weight=control.weight,
                gate=control.gate,
                status=result.status,
                quality=Fraction(result.quality),
                evidence_at=result.evidence_at,
                max_age_days=result.max_age_days,
            )
        )
    return tuple(found)


def score_results(
    library: Library,
    results: Mapping[str, ControlResult],
    as_of: datetime,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> ScoreResult:
    """The score from the results of the check engine at the pack date."""
    require_aware(as_of, "as_of")
    inputs = control_inputs(library, results)
    return score_inputs(inputs, domain_weights(library), as_of, thresholds)


def score_evidence(
    library: Library,
    evidence: Evidence,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> ScoreResult:
    """Run the check engine on the evidence and score its results.

    The entry point of the scoring: a naive `evidence.as_of` is refused with a
    ValueError before any control is evaluated.
    """
    as_of = require_aware(evidence.as_of, "as_of")
    return score_results(library, evaluate_all(library, evidence), as_of, thresholds)
