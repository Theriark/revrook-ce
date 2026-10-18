"""How an exact score is shown: one decimal, never a float (phase 6)."""

from fractions import Fraction
from math import floor

from app.scoring.model import ScoreResult

HALF = Fraction(1, 2)
HUNDRED = Fraction(100)


def format_fixed(value: Fraction, places: int = 1) -> str:
    """An exact value as text with `places` decimals, halves rounded away from zero."""
    scale = 10**places
    units = floor(abs(value) * scale + HALF)
    sign = "-" if value < 0 and units else ""
    if places == 0:
        return f"{sign}{units}"
    whole, part = divmod(units, scale)
    return f"{sign}{whole}.{part:0{places}d}"


def percent(value: Fraction) -> str:
    """A share as whole percent (0.7071 is 71)."""
    return format_fixed(value * HUNDRED, 0)


def headline(result: ScoreResult) -> str:
    """The sentence a report prints beside the score.

    Score and evidence coverage are kept apart so that better evidence is not read
    as better security. With thin evidence the number is a lower bound only.
    """
    coverage = f"evidence coverage {percent(result.coverage)} percent"
    score = format_fixed(result.score)
    if result.best_case is None:
        return f"{result.band}: lower bound {score}, {coverage}"
    line = f"Score {score} (best case {format_fixed(result.best_case)})"
    line += f", band {result.band}, {coverage}"
    if result.capped and result.cap is not None:
        line += f", capped from {format_fixed(result.raw)} by {result.cap.control_id}"
    return line
