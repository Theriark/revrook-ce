"""The inputs, thresholds and results of the scoring engine (phase 6).

Every number here is exact: a share, a weight times a quality or a score is a
`Fraction`, never a float, so the same inputs always give the same digits and a
snapshot can be written again byte for byte. `ControlInput` is all the engine needs
to know about one control, so a stored snapshot can be scored again without the
control file or the check engine of the day.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from app.checks.model import Status

# Why a gate control caps the score: its status, or evidence too old to count.
GATE_FAIL = "fail"
GATE_UNKNOWN = "unknown"
GATE_EXPIRED = "expired"
GATE_PARTIAL = "partial"
GATE_STALE = "stale"


@dataclass(frozen=True)
class Thresholds:
    """The published numbers of the scoring model (rnd-report-3 section 3.5).

    They are stored in every snapshot, so a pack made under other numbers is still
    read under the numbers it was made with. `bands` are (name, lowest score) from
    the best band down; a score below the last one is `lowest_band`.
    """

    cap_fail: int = 49
    cap_partial: int = 69
    min_coverage: Fraction = Fraction(3, 5)
    na_flag_above: Fraction = Fraction(1, 5)
    bands: tuple[tuple[str, int], ...] = (
        ("Strong", 85),
        ("Good", 70),
        ("Fair", 50),
        ("Weak", 30),
    )
    lowest_band: str = "Critical"
    insufficient_band: str = "Insufficient evidence"


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class DomainWeight:
    code: str
    weight: int


@dataclass(frozen=True)
class ControlInput:
    """What one control hands to the scoring engine.

    `quality` is q (1, 0.9 or 0.6; 0 without evidence). `evidence_at` is the time of
    the evidence the status rests on and `max_age_days` the maximum age M of the
    control; both are None when no age can be told, and the control is then fresh.
    """

    control_id: str
    domain: str
    weight: int
    gate: bool
    status: Status
    quality: Fraction
    evidence_at: datetime | None
    max_age_days: int | None


@dataclass(frozen=True)
class ControlScore:
    """One control as scored: s = r x q x f and the weight it earned.

    `counted` is false for a control a reviewer marked not applicable. `covered`
    says fresh evidence stands behind a pass, partial or fail.
    """

    control_id: str
    domain: str
    weight: int
    gate: bool
    status: Status
    quality: Fraction
    freshness: Fraction
    stale: bool
    counted: bool
    covered: bool
    score: Fraction
    contribution: Fraction


@dataclass(frozen=True)
class DomainScore:
    """A domain: the weight it earned out of `possible`, and D (None when dropped).

    A domain whose controls are all not applicable has no D and no weight in the
    overall score.
    """

    code: str
    weight: int
    earned: Fraction
    possible: int
    score: Fraction | None


@dataclass(frozen=True)
class GateCap:
    """The gate control that limits the score, how far and why."""

    control_id: str
    limit: int
    reason: str


@dataclass(frozen=True)
class ScoreResult:
    """The result for one client at one date.

    `raw` is O before the cap and `score` is S = min(O, cap). `upper` is the best
    case; it is shown (`best_case`) only when coverage is high enough, otherwise the
    number is a lower bound and the band is the insufficient-evidence band.
    """

    as_of: datetime
    controls: tuple[ControlScore, ...]
    domains: tuple[DomainScore, ...]
    raw: Fraction
    cap: GateCap | None
    score: Fraction
    coverage: Fraction
    upper: Fraction
    band: str
    insufficient: bool
    na_weight: int
    na_flagged: bool
    dropped_domains: tuple[str, ...]

    @property
    def capped(self) -> bool:
        """Whether a gate lowered the score."""
        return self.cap is not None and self.raw > self.cap.limit

    @property
    def best_case(self) -> Fraction | None:
        """The upper bound, or None when the evidence is too thin to show one."""
        return None if self.insufficient else self.upper
