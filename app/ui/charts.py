"""The view models of the interactive charts: pure functions, no database and no
request (docs/design-system.md, Charts).

Every chart is drawn on the server as SVG with a table of its numbers under it, from
data the application already stores: the stored reports, the live views and the
evidence rows the pages read anyway. `app/static/js/charts.js` only layers the
tooltips, the keyboard, the series toggles and the in-place range swaps on what is
in the page. What a tooltip says is written here as text, so the words a person
reads on hover are the ones the table shows and nothing is computed twice.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from app.reports.status import StatusLabel
from app.reports.view import iso_date
from app.scoring.display import format_fixed
from app.ui.clientlist import (
    BAND_KEYS,
    BAND_NAMES,
    NO_REPORT_KEY,
    NO_REPORT_NAME,
    ClientCard,
    band_key,
)
from app.ui.common import FormError
from app.ui.dashboard import HISTORY_DAYS, ReportPoint
from app.ui.viewmodels import SourceRow

# The ranges of the Home trend chart, in days; the longest is the one drawn by
# default and the one the stored reports are read for (HISTORY_DAYS).
RANGE_DAYS = (7, 30, HISTORY_DAYS)
RANGE_WORDS = {7: "7 days", 30: "30 days", HISTORY_DAYS: "90 days"}
# The ranges of the score history of one client: the last quarter, the last year,
# or every report the client has.
HISTORY_RANGES = (("90", "90 days"), ("365", "A year"), ("all", "All reports"))
HISTORY_KEYS = tuple(key for key, _ in HISTORY_RANGES)
DEFAULT_HISTORY = "all"
NEVER_IMPORTED = "Never imported"


def read_days(text: str) -> int:
    """The range of the trend chart; FormError (422) when it is not one known."""
    value = text.strip()
    if not value:
        return HISTORY_DAYS
    choices = ", ".join(str(days) for days in RANGE_DAYS)
    if value not in {str(days) for days in RANGE_DAYS}:
        raise FormError(f"Days must be one of {choices}.")
    return int(value)


def read_range(text: str) -> str:
    """The range of the score history; FormError (422) when it is not one known."""
    value = text.strip()
    if not value:
        return DEFAULT_HISTORY
    if value not in HISTORY_KEYS:
        raise FormError(f"Range must be one of {', '.join(HISTORY_KEYS)}.")
    return value


def history_days(key: str, points: Sequence[ReportPoint], now: datetime) -> int:
    """How many days the history chart spans: the number of the range, or for
    "all" from the oldest report to now (a quarter when there is no report), and
    at least a week, so the dates of the time axis never repeat one day."""
    if key != "all":
        return int(key)
    if not points:
        return HISTORY_DAYS
    oldest = min(point.as_of for point in points)
    return max((now - oldest).days + 1, RANGE_DAYS[0])


def _percent(part: int | Fraction, whole: int | Fraction) -> str:
    """A share of a scale as a percentage with two decimals, capped at 100."""
    if whole <= 0:
        return "0"
    return format_fixed(min(Fraction(part) * 100 / Fraction(whole), Fraction(100)), 2)


# --- the age of every export (the evidence page) ----------------------------------


@dataclass(frozen=True)
class AgeBar:
    """One source of a client: how old its newest export is against its stale date.

    `width` and `mark` are percentages of one shared scale, so every bar of the page
    is read against the same ruler; the mark is where the export goes stale.
    """

    code: str
    name: str
    state: StatusLabel
    age_days: int | None
    stale_days: int | None
    width: str
    mark: str
    words: str
    tip: str

    @property
    def imported(self) -> bool:
        return self.age_days is not None


def age_words(age_days: int) -> str:
    if age_days <= 0:
        return "captured today"
    if age_days == 1:
        return "1 day old"
    return f"{age_days} days old"


def age_bars(rows: Sequence[SourceRow], now: datetime) -> list[AgeBar]:
    """One bar per source row, in the order of the rows (by name).

    The scale is twice the longest stale window, where an export counts for
    nothing (`freshness` in app/scoring/engine.py), or the oldest age when that is
    longer; so every stale mark sits at most halfway along its track, never on its
    rounded end, and a bar that fills the track is evidence worth nothing.
    """
    ages: dict[str, int] = {}
    windows: dict[str, int] = {}
    for row in rows:
        if row.captured_at is None:
            continue
        ages[row.code] = max((now - row.captured_at).days, 0)
        if row.expires_at is not None:
            windows[row.code] = max((row.expires_at - row.captured_at).days, 0)
    scale = max([*ages.values(), *(2 * window for window in windows.values()), 1])
    bars: list[AgeBar] = []
    for row in rows:
        age = ages.get(row.code)
        window = windows.get(row.code)
        if age is None or row.captured_at is None:
            bars.append(
                AgeBar(
                    code=row.code,
                    name=row.name,
                    state=row.state,
                    age_days=None,
                    stale_days=None,
                    width="0",
                    mark="",
                    words=NEVER_IMPORTED,
                    tip=f"{row.name}\n{row.state.text}\nNo export has been imported.",
                )
            )
            continue
        words = age_words(age)
        lines = [
            row.name,
            row.state.text,
            f"Newest export {iso_date(row.captured_at)}, {words}",
        ]
        if window is not None and row.expires_at is not None:
            words = f"{words}, stale after {window} days"
            lines.append(f"Stale after {window} days: {iso_date(row.expires_at)}")
        bars.append(
            AgeBar(
                code=row.code,
                name=row.name,
                state=row.state,
                age_days=age,
                stale_days=window,
                width=_percent(age, scale),
                mark="" if window is None else _percent(window, scale),
                words=words,
                tip="\n".join(lines),
            )
        )
    return bars


# --- the clients by band (the clients list) ----------------------------------------


@dataclass(frozen=True)
class BandCount:
    """One band of the scoring model across the list: how many clients sit in it
    at their last report, and the length of its bar against the fullest band."""

    key: str
    name: str
    count: int
    width: str

    @property
    def tip(self) -> str:
        clients = "client" if self.count == 1 else "clients"
        if self.key == NO_REPORT_KEY:
            return f"{self.name}\n{self.count} {clients}"
        return f"{self.name}\n{self.count} {clients} at the last report"


class BandCounts(list[BandCount]):
    """The bars of the clients list, in order, and `unclassified`: how many clients
    sit in a band the model does not know, so no bar holds them."""

    unclassified: int = 0


def band_counts(cards: Sequence[ClientCard]) -> BandCounts:
    """Every band of the model in its order, then the clients without a report.

    A stored band the model does not know (a report of another ruleset) has no bar
    and no filter to open, so it is left out of the bars and counted in
    `unclassified` for the note under them; the client stays in the list.
    """
    found = dict.fromkeys((*BAND_KEYS, NO_REPORT_KEY), 0)
    for card in cards:
        key = NO_REPORT_KEY if card.report is None else band_key(card.report.band)
        if key in found:
            found[key] += 1
    fullest = max(found.values(), default=0)
    names = dict(zip(BAND_KEYS, BAND_NAMES, strict=True))
    names[NO_REPORT_KEY] = NO_REPORT_NAME
    bars = BandCounts(
        BandCount(key, names[key], count, _percent(count, fullest))
        for key, count in found.items()
    )
    bars.unclassified = unclassified_count(cards)
    return bars


def unclassified_count(cards: Sequence[ClientCard]) -> int:
    """The clients whose last report is in a band the model does not know.

    No bar counts them, so without this the bars add up to fewer clients than the
    list holds and nothing says why.
    """
    known = {*BAND_KEYS, NO_REPORT_KEY}
    return sum(
        1
        for card in cards
        if card.report is not None and band_key(card.report.band) not in known
    )
