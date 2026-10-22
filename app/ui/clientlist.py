"""The view model of the clients list: pure functions, no database and no request.

The list shows every active client with the number of its exports, the date of its
newest evidence and, once a report has been made for it, the posture of that last
stored report: the score ring, the band and the controls by status as pills with
their counts. The posture is read from the stored snapshot with the same scoring the
report was made with (`score_snapshot`, `previous_labels`); nothing here runs a check
or adds a rule. Searching, filtering, sorting and paging work on the rows already
read, in plain Python, so the page stays one query for the clients and one for their
newest snapshots.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from fractions import Fraction
from typing import Any
from urllib.parse import urlencode

from app.reports.status import (
    COUNTED_LABELS,
    NEEDS_ATTENTION,
    NOT_CHECKED,
    NOT_PROTECTED,
    PROTECTED,
    StatusLabel,
)
from app.reports.view import iso_date
from app.scoring.display import format_fixed
from app.scoring.model import DEFAULT_THRESHOLDS
from app.scoring.snapshot import (
    SnapshotError,
    SnapshotInput,
    document_bytes,
    parse_snapshot,
    score_snapshot,
)
from app.ui.common import FormError
from app.ui.dashboard import ring_dash
from app.ui.viewmodels import previous_labels

PAGE_SIZE = 50
MAX_SEARCH = 200
MAX_PAGE_DIGITS = 6
FILTERS = (
    ("all", "All clients"),
    ("needs-work", "Needs work"),
    ("no-report", "No report yet"),
    ("no-evidence", "No evidence yet"),
)
FILTER_KEYS = tuple(key for key, _ in FILTERS)
SORTS = ("name", "score", "evidence")
SORT_WORDS = {"name": "name", "score": "score", "evidence": "newest evidence"}
# The order a column is sorted in first: the worst score and the newest evidence
# are what the person looks for.
FIRST_ORDER = {"name": "asc", "score": "asc", "evidence": "desc"}
ORDERS = ("asc", "desc")
DENSITIES = ("comfortable", "compact")
NO_EVIDENCE = StatusLabel("not-checked", "No evidence yet", "question")
ALL_PROTECTED = StatusLabel("protected", "All checked controls protected", "check")
# The bands of the scoring model in their order, each with the key of its filter
# (`?band=strong`), and the key of the clients without a report.
BAND_NAMES = tuple(name for name, _ in DEFAULT_THRESHOLDS.bands) + (
    DEFAULT_THRESHOLDS.lowest_band,
    DEFAULT_THRESHOLDS.insufficient_band,
)
BAND_KEYS = tuple(name.split()[0].lower() for name in BAND_NAMES)
NO_REPORT_KEY = "none"
NO_REPORT_NAME = "No report yet"
BAND_CHOICES = (*BAND_KEYS, NO_REPORT_KEY)


def band_key(band: str) -> str:
    """The filter key of a band name ("Insufficient evidence" is "insufficient")."""
    return band.split()[0].lower() if band else NO_REPORT_KEY


def read_band(text: str) -> str:
    """The band filter of the list; empty for none, FormError (422) if unknown."""
    value = text.strip()
    if value and value not in BAND_CHOICES:
        raise FormError(f"Band must be one of {', '.join(BAND_CHOICES)}.")
    return value


@dataclass(frozen=True)
class LastReport:
    """The last stored report of a client, as the list shows it."""

    as_of: datetime
    score: Fraction
    score_text: str
    score_share: int
    band: str
    insufficient: bool
    counts: tuple[tuple[StatusLabel, int], ...]

    @property
    def ring_dash(self) -> str:
        return ring_dash(self.score_share)

    @property
    def day(self) -> str:
        return iso_date(self.as_of)

    def of(self, label: StatusLabel) -> int:
        return sum(count for item, count in self.counts if item == label)

    @property
    def needs_work(self) -> int:
        return self.of(NOT_PROTECTED) + self.of(NEEDS_ATTENTION)

    @property
    def pills(self) -> tuple[StatusLabel, ...]:
        """The counts that need a look as status pills, worst first; one pill of
        reassurance when every checked control is protected."""
        found: list[StatusLabel] = []
        not_protected = self.of(NOT_PROTECTED)
        if not_protected:
            found.append(replace(NOT_PROTECTED, text=f"{not_protected} not protected"))
        attention = self.of(NEEDS_ATTENTION)
        if attention:
            verb = "needs" if attention == 1 else "need"
            found.append(replace(NEEDS_ATTENTION, text=f"{attention} {verb} attention"))
        unchecked = self.of(NOT_CHECKED)
        if unchecked:
            found.append(replace(NOT_CHECKED, text=f"{unchecked} not checked"))
        if not found and self.of(PROTECTED):
            found.append(ALL_PROTECTED)
        return tuple(found)


def last_report_of(snapshot: SnapshotInput) -> LastReport:
    """The posture of one stored snapshot, scored as its report was."""
    result = score_snapshot(snapshot)
    labels = list(previous_labels(snapshot).values())
    counts = tuple(
        (label, sum(1 for item in labels if item == label)) for label in COUNTED_LABELS
    )
    return LastReport(
        as_of=snapshot.as_of,
        score=result.score,
        score_text=format_fixed(result.score),
        score_share=max(0, min(int(result.score), 100)),
        band=result.band,
        insufficient=result.insufficient,
        counts=counts,
    )


def last_reports(
    rows: Iterable[tuple[int, Mapping[str, Any]]],
) -> dict[int, LastReport]:
    """The last report of each client from its newest stored snapshot document; a
    document that cannot be read is skipped, so one bad row never hides the list."""
    found: dict[int, LastReport] = {}
    for client_id, document in rows:
        try:
            snapshot = parse_snapshot(document_bytes(dict(document)))
        except SnapshotError:
            continue
        found[client_id] = last_report_of(snapshot)
    return found


@dataclass(frozen=True)
class ClientCard:
    """One row of the list."""

    id: int
    name: str
    exports: int
    newest: datetime | None
    days_old: int | None
    report: LastReport | None

    @property
    def needs_work(self) -> bool:
        return self.report is not None and self.report.needs_work > 0

    @property
    def age_text(self) -> str:
        """How old the newest evidence is, in words."""
        if self.days_old is None:
            return ""
        if self.days_old <= 0:
            return "today"
        if self.days_old == 1:
            return "yesterday"
        return f"{self.days_old} days ago"


@dataclass(frozen=True)
class ListQuery:
    """What the person asked the list for; every value is one of the known ones."""

    q: str = ""
    show: str = "all"
    sort: str = "name"
    order: str = "asc"
    density: str = "comfortable"
    page: int = 1
    band: str = ""

    def params(self, **changes: object) -> str:
        """The query part of the list's address with these changes, starting with
        a question mark; a value that is the default is left out, and the template
        writes the path (`/clients`) itself."""
        values = {**asdict(self), **changes}
        default = asdict(ListQuery())
        kept = {
            key: str(value) for key, value in values.items() if value != default[key]
        }
        return f"?{urlencode(kept)}" if kept else ""

    def next_order(self, sort: str) -> str:
        """The order a click on this column's heading asks for."""
        if sort != self.sort:
            return FIRST_ORDER[sort]
        return "desc" if self.order == "asc" else "asc"

    def aria_sort(self, sort: str) -> str:
        """The aria-sort value of a column heading; empty when it is not sorted."""
        if sort != self.sort:
            return ""
        return "ascending" if self.order == "asc" else "descending"

    @property
    def sort_words(self) -> str:
        direction = "A to Z" if self.order == "asc" else "Z to A"
        if self.sort == "score":
            direction = "lowest first" if self.order == "asc" else "highest first"
        elif self.sort == "evidence":
            direction = "oldest first" if self.order == "asc" else "newest first"
        return f"{SORT_WORDS[self.sort]}, {direction}"


def read_query(
    q: str,
    show: str,
    sort: str,
    order: str,
    density: str,
    page: str,
    band: str = "",
) -> ListQuery:
    """The query of the list; FormError (422) when a value is not one of the known."""
    if show not in FILTER_KEYS:
        raise FormError(f"Show must be one of {', '.join(FILTER_KEYS)}.")
    if sort not in SORTS:
        raise FormError(f"Sort must be one of {', '.join(SORTS)}.")
    if order not in ORDERS:
        raise FormError("Order must be asc or desc.")
    if density not in DENSITIES:
        raise FormError("Density must be comfortable or compact.")
    number = page.strip()
    if not number.isdecimal() or len(number) > MAX_PAGE_DIGITS or int(number) < 1:
        raise FormError("Page must be a whole number from 1.")
    return ListQuery(
        q=" ".join(q.split())[:MAX_SEARCH],
        show=show,
        sort=sort,
        order=order,
        density=density,
        page=int(number),
        band=read_band(band),
    )


def matches(card: ClientCard, query: ListQuery) -> bool:
    """Whether a client is shown under this search, filter and band."""
    if query.q and query.q.casefold() not in card.name.casefold():
        return False
    if query.band:
        key = NO_REPORT_KEY if card.report is None else band_key(card.report.band)
        if key != query.band:
            return False
    if query.show == "needs-work":
        return card.needs_work
    if query.show == "no-report":
        return card.report is None
    if query.show == "no-evidence":
        return card.newest is None
    return True


def _by_name(cards: Iterable[ClientCard], descending: bool) -> list[ClientCard]:
    return sorted(
        cards, key=lambda card: (card.name.casefold(), card.id), reverse=descending
    )


def select_rows(cards: Sequence[ClientCard], query: ListQuery) -> list[ClientCard]:
    """The clients that match, in the order asked for. A client without the value a
    column sorts by (no report, no evidence) comes last whichever the order."""
    kept = [card for card in cards if matches(card, query)]
    descending = query.order == "desc"
    if query.sort == "score":
        scored = [card for card in kept if card.report is not None]
        scored.sort(
            key=lambda card: (
                card.report.score if card.report else Fraction(0),
                card.name.casefold(),
                card.id,
            ),
            reverse=descending,
        )
        rest = [card for card in kept if card.report is None]
        return scored + _by_name(rest, False)
    if query.sort == "evidence":
        dated = [card for card in kept if card.newest is not None]
        dated.sort(
            key=lambda card: (
                card.newest or datetime.min,
                card.name.casefold(),
                card.id,
            ),
            reverse=descending,
        )
        rest = [card for card in kept if card.newest is None]
        return dated + _by_name(rest, False)
    return _by_name(kept, descending)


def filter_counts(cards: Sequence[ClientCard], query: ListQuery) -> dict[str, int]:
    """How many clients each filter would show under the current search."""
    return {
        key: sum(1 for card in cards if matches(card, replace(query, show=key)))
        for key in FILTER_KEYS
    }


@dataclass(frozen=True)
class Page:
    """One page of the rows."""

    items: list[ClientCard]
    number: int
    pages: int
    total: int
    size: int = PAGE_SIZE

    @property
    def start(self) -> int:
        return 0 if not self.total else (self.number - 1) * self.size + 1

    @property
    def end(self) -> int:
        return min(self.number * self.size, self.total)


def paginate(rows: Sequence[ClientCard], number: int, size: int = PAGE_SIZE) -> Page:
    """The page `number` of the rows; a number past the end gives the last page."""
    pages = max(1, -(-len(rows) // size))
    number = min(max(number, 1), pages)
    start = (number - 1) * size
    return Page(list(rows[start : start + size]), number, pages, len(rows), size)
