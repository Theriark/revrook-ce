"""The review horizon of the exceptions register (THE-1360), drawn by exceptions.html.

The coming year as one line: today at its left end, every open exception a merlon
standing at its review date, and the exceptions past their date stacked before
today. The drawing is HORIZON_WIDTH units wide; its first OVERDUE_GUTTER units hold
the overdue ones and the year after today runs to the right edge. Merlons closer to
each other than a merlon and its gap stack upwards, at most HORIZON_LEVELS high (the
register under the drawing lists every one). An exception due more than a year away
is counted, not drawn.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple, Protocol

HORIZON_DAYS = 365
HORIZON_WIDTH = 640
OVERDUE_GUTTER = 28
HORIZON_AXIS = 52
MARK_WIDTH = 10
MARK_GAP = 2
MARK_HEIGHT = 12
MARK_STEP = 14
HORIZON_LEVELS = 3
SOON_DAYS = 30
# A month this close to the right end of the drawing is named up to the edge
# instead of around its tick: "Jan 2028" centred on the last day ran 20 to 23px
# past the drawing and to within 2px of the border of its card (THE-1401). Half
# of "Jan 2027" at 11px is 24 units; a three-letter name at 26 units on a phone,
# 20 units.
EDGE_ROOM = 28
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class DueRow(Protocol):
    """What the horizon reads of a row of the register (app.ui.clients)."""

    @property
    def control_id(self) -> str: ...

    @property
    def review_date(self) -> date: ...

    @property
    def overdue(self) -> bool: ...

    @property
    def closed(self) -> bool: ...


@dataclass(frozen=True)
class Due:
    """A row of the register with only what the horizon reads."""

    control_id: str
    review_date: date
    overdue: bool
    closed: bool


@dataclass(frozen=True)
class HorizonMark:
    """One merlon: its top left corner, and overdue, soon (30 days) or later."""

    x: str
    y: str
    state: str
    control_id: str
    review_date: date


class Month(NamedTuple):
    """The first day of a month ahead: the x of its tick and its name, with the
    year when it is a January."""

    x: str
    label: str

    @property
    def at_edge(self) -> bool:
        """Whether the name ends at the right edge of the drawing (EDGE_ROOM)."""
        return float(self.x) > HORIZON_WIDTH - EDGE_ROOM

    @property
    def text_x(self) -> str:
        return str(HORIZON_WIDTH) if self.at_edge else self.x

    @property
    def anchor(self) -> str:
        return "end" if self.at_edge else "middle"

    @property
    def name(self) -> str:
        return self.label.split(" ", 1)[0]

    @property
    def year(self) -> str:
        """The year of a January, drawn in its own tspan that a phone hides; a
        January at the right edge is named without it, as its neighbour December
        leaves no room for it there (the sentence above and the register carry
        every date)."""
        _, _, year = self.label.partition(" ")
        return "" if self.at_edge else year


@dataclass(frozen=True)
class Horizon:
    """The merlons, the first day of each month ahead and the counts in words."""

    marks: tuple[HorizonMark, ...]
    months: tuple[Month, ...]
    today_x: int
    overdue: int
    soon: int
    within_year: int
    beyond_year: int


def day_x(days: int) -> float:
    """The x of the middle of the day `days` after today (0 is today)."""
    span = HORIZON_WIDTH - OVERDUE_GUTTER - MARK_WIDTH
    within = min(max(days, 0), HORIZON_DAYS)
    return OVERDUE_GUTTER + MARK_WIDTH / 2 + span * within / HORIZON_DAYS


def month_starts(today: date) -> tuple[Month, ...]:
    """The x and the name of the first day of every month in the year ahead."""
    found: list[Month] = []
    year, month = today.year, today.month
    while True:
        month += 1
        if month > 12:
            year, month = year + 1, 1
        days = (date(year, month, 1) - today).days
        if days > HORIZON_DAYS:
            return tuple(found)
        label = f"{MONTHS[0]} {year}" if month == 1 else MONTHS[month - 1]
        found.append(Month(f"{day_x(days):.1f}", label))


def level_of(middle: float, placed: list[tuple[float, int]]) -> int:
    """The lowest free level for a merlon at `middle`, given those already placed.

    A level is taken when a merlon on it stands closer than a merlon and its gap,
    so two merlons a few days apart stack instead of overlapping (THE-1375).
    """
    level = 0
    while level < HORIZON_LEVELS - 1 and any(
        at == level and abs(other - middle) < MARK_WIDTH + MARK_GAP
        for other, at in placed
    ):
        level += 1
    return level


def review_horizon(rows: Iterable[DueRow], today: date) -> Horizon:
    """Where every open row of the register stands in the year after `today`."""
    placed: list[tuple[float, int]] = []
    marks: list[HorizonMark] = []
    overdue = soon = within = beyond = 0
    for row in sorted(
        (item for item in rows if not item.closed),
        key=lambda item: (item.review_date, item.control_id),
    ):
        days = (row.review_date - today).days
        if row.overdue:
            overdue += 1
            middle = OVERDUE_GUTTER / 2
            state = "overdue"
        elif days > HORIZON_DAYS:
            beyond += 1
            continue
        else:
            within += 1
            middle = day_x(days)
            state = "soon" if days <= SOON_DAYS else "later"
            soon += state == "soon"
        level = level_of(middle, placed)
        placed.append((middle, level))
        top = HORIZON_AXIS - MARK_HEIGHT - level * MARK_STEP
        x = f"{middle - MARK_WIDTH / 2:.1f}"
        marks.append(HorizonMark(x, str(top), state, row.control_id, row.review_date))
    return Horizon(
        tuple(marks),
        month_starts(today),
        OVERDUE_GUTTER,
        overdue,
        soon,
        within,
        beyond,
    )
