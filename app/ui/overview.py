"""The view model of the client overview: pure functions over the live report view.

The overview reads the client as it is today (`app.posture.load_live`, then
`view_of`) and shows the parts of that view a person wants first: the posture ring,
the controls by status, the domains as stacked bars with their weight and score, the
most urgent controls and the freshness of the evidence. Nothing is stored and no
number is rounded differently from the report the same view would print.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.reports.status import PROTECTED, StatusLabel
from app.reports.view import DomainRow
from app.ui.dashboard import Segment, segments_of


@dataclass(frozen=True)
class DomainLine:
    """One domain of the library for this client: its bar, weight and score."""

    code: str
    name: str
    weight: int
    score_text: str
    counts: tuple[tuple[StatusLabel, int], ...]

    @property
    def total(self) -> int:
        return sum(count for _, count in self.counts)

    @property
    def protected(self) -> int:
        return sum(count for label, count in self.counts if label == PROTECTED)

    @property
    def segments(self) -> tuple[Segment, ...]:
        return segments_of(self.counts)


def domain_lines(rows: Iterable[DomainRow]) -> list[DomainLine]:
    """The domains of the view in the order of the control library."""
    return [
        DomainLine(row.code, row.name, row.weight, row.score_text, row.counts)
        for row in rows
    ]
