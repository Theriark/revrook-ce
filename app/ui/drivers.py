"""What moves the posture score: the hundred points of a client, split by cause.

Nothing here is stored or estimated. The score of the scoring engine
(docs/scoring-engine.md) is the domain-weighted mean of the domain scores, held
down by a gate control when one caps it:

    O = sum over the domains d of w_d x D_d / W,  D_d = 100 x earned_d / possible_d
    S = min(O, cap)

so the points between the score and a hundred are exactly the points every counted
control does not earn, weighted the way the engine weights it, plus what the cap
holds back. One control earns s = r x q x f of its weight (status, evidence type,
freshness), and what it does not earn splits without a remainder:

    1 - r q f = (1 - r) + r (1 - q) + r q (1 - f)

The first part is its status (not protected, partly met or not checked), the
second the type of its evidence (a manual artefact or an attestation counts for
less than an automatic export), the third the age of that evidence. The sums are
Fractions, so earned and lost always add up to a hundred.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from app.checks.engine import STATUS_VALUE
from app.scoring.display import format_fixed
from app.scoring.model import ScoreResult

HUNDRED = Fraction(100)
ZERO = Fraction(0)
ONE = Fraction(1)
TOP_CONTROLS = 3


@dataclass(frozen=True)
class Driver:
    """One cause of lost points: its key (the class of its segment) and words."""

    key: str
    text: str
    meaning: str


NOT_PROTECTED = Driver(
    "not-protected", "Not protected", "a control that fails earns none of its weight"
)
PARTLY_MET = Driver("partly-met", "Partly met", "a partial pass earns half its weight")
NOT_CHECKED = Driver(
    "not-checked", "Not checked", "a control without evidence earns nothing"
)
EVIDENCE_TYPE = Driver(
    "evidence-type",
    "Evidence type",
    "a manual artefact counts 0.9 and an attestation 0.6 of an automatic export",
)
EVIDENCE_AGE = Driver(
    "evidence-age",
    "Evidence age",
    "evidence past its maximum age counts for less, and for nothing at twice it",
)
GATE_CAP = Driver(
    "gate-cap", "Gate cap", "a gate control that is not met holds the score down"
)
DRIVERS = (
    NOT_PROTECTED,
    PARTLY_MET,
    NOT_CHECKED,
    EVIDENCE_TYPE,
    EVIDENCE_AGE,
    GATE_CAP,
)
STATUS_DRIVER = {"fail": NOT_PROTECTED, "partial": PARTLY_MET, "unknown": NOT_CHECKED}


@dataclass(frozen=True)
class Loss:
    """The points one driver costs, and where its segment sits on the bar."""

    driver: Driver
    points: Fraction
    x: str
    width: str

    @property
    def text(self) -> str:
        return format_fixed(self.points)


@dataclass(frozen=True)
class ControlLoss:
    """One control and the points of the score it does not earn today."""

    control_id: str
    title: str
    points: Fraction
    gate: bool

    @property
    def text(self) -> str:
        return format_fixed(self.points)


@dataclass(frozen=True)
class ScoreDrivers:
    """The hundred points of one score: earned, and lost by driver.

    `losses` keeps the order of DRIVERS and leaves out a driver that costs
    nothing; `top` is the few controls that cost the most, most first.
    """

    earned: Fraction
    losses: tuple[Loss, ...]
    top: tuple[ControlLoss, ...]
    cap_control: str | None
    cap_limit: int | None

    @property
    def earned_text(self) -> str:
        return format_fixed(self.earned)

    @property
    def earned_width(self) -> str:
        return _width(self.earned)

    @property
    def biggest(self) -> Loss | None:
        """The driver that costs the most points (the first of DRIVERS on a tie)."""
        return max(self.losses, key=lambda loss: loss.points, default=None)

    @property
    def lost(self) -> Fraction:
        return sum((loss.points for loss in self.losses), ZERO)

    @property
    def label(self) -> str:
        """The bar in words: what is earned, then every driver, most first."""
        parts = [f"{self.earned_text} of 100 points earned"]
        ranked = sorted(self.losses, key=lambda loss: loss.points, reverse=True)
        parts += [f"{loss.text} lost to {loss.driver.text.lower()}" for loss in ranked]
        return ", ".join(parts) + "."

    def points_of(self, key: str) -> Fraction:
        for loss in self.losses:
            if loss.driver.key == key:
                return loss.points
        return ZERO

    def text_of(self, key: str) -> str:
        """The points of one driver as the table writes them (0.0 when none)."""
        return format_fixed(self.points_of(key))


def _width(points: Fraction) -> str:
    """A share of the 100-wide bar, rounded for the SVG (the words keep the exact)."""
    return f"{float(points):.2f}"


def _bar(earned: Fraction, lost: Mapping[str, Fraction]) -> tuple[Loss, ...]:
    """The segments after the earned one, left to right in the order of DRIVERS."""
    found: list[Loss] = []
    x = earned
    for driver in DRIVERS:
        points = lost.get(driver.key, ZERO)
        if points <= 0:
            continue
        found.append(Loss(driver, points, _width(x), _width(points)))
        x += points
    return tuple(found)


def drivers_of(
    result: ScoreResult, titles: Mapping[str, str] | None = None
) -> ScoreDrivers | None:
    """Split the score of `result` by cause; None when no domain is counted (every
    control not applicable), where there are no points to split."""
    weights = {
        domain.code: (domain.weight, domain.possible)
        for domain in result.domains
        if domain.score is not None and domain.possible
    }
    total = sum(weight for weight, _ in weights.values())
    if not total:
        return None
    lost: defaultdict[str, Fraction] = defaultdict(Fraction)
    per_control: list[ControlLoss] = []
    names = titles or {}
    for item in result.controls:
        if not item.counted or item.domain not in weights:
            continue
        weight, possible = weights[item.domain]
        share = HUNDRED * weight * item.weight / (total * possible)
        status = Fraction(STATUS_VALUE[item.status])
        parts = (
            (STATUS_DRIVER.get(item.status), ONE - status),
            (EVIDENCE_TYPE, status * (ONE - item.quality)),
            (EVIDENCE_AGE, status * item.quality * (ONE - item.freshness)),
        )
        control_points = ZERO
        for driver, part in parts:
            if driver is None or part <= 0:
                continue
            lost[driver.key] += share * part
            control_points += share * part
        if control_points > 0:
            per_control.append(
                ControlLoss(
                    item.control_id,
                    names.get(item.control_id, ""),
                    control_points,
                    item.gate,
                )
            )
    cap = result.cap if result.capped else None
    if cap is not None:
        lost[GATE_CAP.key] = result.raw - result.score
    earned = result.score
    per_control.sort(key=lambda found: (-found.points, found.control_id))
    return ScoreDrivers(
        earned=earned,
        losses=_bar(earned, lost),
        top=tuple(per_control[:TOP_CONTROLS]),
        cap_control=cap.control_id if cap is not None else None,
        cap_limit=cap.limit if cap is not None else None,
    )


@dataclass(frozen=True)
class PortfolioDrivers:
    """The mean split over the clients that have evidence: the mean score and the
    mean points of each driver, which add up to a hundred as each client does."""

    clients: int
    drivers: ScoreDrivers


def portfolio_of(found: Iterable[ScoreDrivers | None]) -> PortfolioDrivers | None:
    """The mean of the splits that exist; None when there is none."""
    splits: Sequence[ScoreDrivers] = [item for item in found if item is not None]
    if not splits:
        return None
    count = len(splits)
    earned = sum((item.earned for item in splits), ZERO) / count
    lost = {
        driver.key: sum((item.points_of(driver.key) for item in splits), ZERO) / count
        for driver in DRIVERS
    }
    return PortfolioDrivers(
        clients=count,
        drivers=ScoreDrivers(
            earned=earned,
            losses=_bar(earned, lost),
            top=(),
            cap_control=None,
            cap_limit=None,
        ),
    )
