"""The view model of the Home dashboard: pure functions, no database and no request.

Home shows the whole book of clients at once: how each client stands today (the
posture ring), which controls need work first across every client, how the scores
moved over the last 90 days of stored reports, which domains carry the gaps and what
changed recently. Everything is computed from the same views, labels and snapshots
the client pages and the reports use: nothing is stored, no number is rounded
differently, and no rule of evidence changes. Coordinates of a drawing are floats;
every score and count stays exact until it is written as text.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from math import pi
from typing import Any

from app.models import AuditEvent
from app.reports.render import REPORT_NAMES
from app.reports.status import (
    COUNTED_LABELS,
    NEEDS_ATTENTION,
    NOT_PROTECTED,
    PROTECTED,
    StatusLabel,
)
from app.reports.view import DomainRow, ReportView, iso_date
from app.scoring.display import format_fixed, percent
from app.scoring.snapshot import (
    SnapshotError,
    SnapshotInput,
    document_bytes,
    parse_snapshot,
    score_snapshot,
    trend,
)
from app.ui.viewmodels import (
    CURRENT,
    EXPIRED,
    MISSING,
    STALE,
    SourceRow,
    flags_of,
    previous_labels,
)

HISTORY_DAYS = 90
WEEKS = 12
MAX_ATTENTION = 8
MAX_TREND_LINES = 6
MAX_EVENTS = 10
MAX_SNAPSHOTS = 400
RING_RADIUS = 30
SPARK_WIDTH = 96
SPARK_HEIGHT = 28
SPARK_PAD = 2
CHART_WIDTH = 640
CHART_HEIGHT = 220
CHART_LEFT = 36
CHART_RIGHT = 150
CHART_TOP = 12
CHART_BOTTOM = 28
# The distance between two stacked labels at the ends of the lines, in chart
# units: a label is 12 units of text in a box of about 14, so at 14 two labels
# touched (seen at 768px); 18 leaves 4 units of air, and six fit in the plot.
LABEL_GAP = 18
NAME_LENGTH = 20
DASHES = ("", "6 3", "2 3", "9 3 2 3", "1 3", "12 4")
NEEDS_WORK = (NOT_PROTECTED, NEEDS_ATTENTION)
URGENCY = {NOT_PROTECTED: 0, NEEDS_ATTENTION: 1}
# The audit actions that change a client, its evidence or its reports, in words.
EVENT_WORDS = {
    "client.created": "Client added",
    "client.deleted": "Client deleted",
    "evidence.added": "Evidence imported",
    "evidence.revised": "Evidence revised",
    "import_profile.created": "Mapping profile saved",
    "snapshot.created": "Report snapshot made",
    "report.export": "Report exported",
    "exception.added": "Exception added",
    "exception.closed": "Exception closed",
    "settings.msp_name": "MSP name changed",
    "settings.reminder_recipient": "Reminder address changed",
}
EVENT_PAGES = {
    "evidence.added": "evidence",
    "evidence.revised": "evidence",
    "exception.added": "exceptions",
    "exception.closed": "exceptions",
    "snapshot.created": "reports",
    "report.export": "exports",
}
DELETED_CLIENT = "a deleted client"
SYSTEM_ACTOR = "The worker"
UNKNOWN_ACTOR = "A removed user"


def deleted_client_name(client_id: int) -> str:
    """How an entry of the audit trail names a client that is gone.

    Deleting a client removes every row of it, its name included, and the audit
    trail keeps counts and never content (tests/test_evidence_deletion.py checks
    that the name is gone from a dump of the database). So the name cannot be
    shown again; the number of the client is what tells the entries of one
    deleted client from those of another.
    """
    return f"{DELETED_CLIENT} (client {client_id})"


# --- the posture ring ---------------------------------------------------------------


def ring_dash(share: int, radius: int = RING_RADIUS) -> str:
    """The stroke-dasharray that fills `share` percent of a ring of `radius`."""
    circumference = 2 * pi * radius
    filled = circumference * max(0, min(share, 100)) / 100
    return f"{filled:.1f} {circumference:.1f}"


@dataclass(frozen=True)
class ClientPosture:
    """One client as the dashboard shows it: the ring, the band and the counts."""

    client_id: int
    name: str
    score_text: str
    score_share: int
    band: str
    insufficient: bool
    coverage_percent: str
    counts: tuple[tuple[StatusLabel, int], ...]
    change_text: str
    evidence: int
    protected_before: int | None
    needs_work_before: int | None

    @property
    def ring_dash(self) -> str:
        return ring_dash(self.score_share)

    @property
    def protected(self) -> int:
        return sum(count for label, count in self.counts if label == PROTECTED)

    @property
    def needs_work(self) -> int:
        return sum(count for label, count in self.counts if label in NEEDS_WORK)

    @property
    def counted(self) -> int:
        return sum(count for _, count in self.counts)


def change_words(current: SnapshotInput, earlier: SnapshotInput | None) -> str:
    """How the score moved since the last stored report, in words."""
    if earlier is None:
        return "No earlier report"
    since = iso_date(earlier.as_of)
    change = trend(earlier, current)
    if change is None:
        return f"Not compared with the report of {since}: other rules"
    text = format_fixed(abs(change.score_change))
    if text == "0.0":
        return f"Unchanged since {since}"
    direction = "Up" if change.score_change > 0 else "Down"
    return f"{direction} {text} since {since}"


def posture_of(
    client_id: int,
    name: str,
    view: ReportView,
    earlier: SnapshotInput | None,
    evidence: int,
) -> ClientPosture:
    """The posture of one client from its live view and its last stored report."""
    result = view.result
    before = previous_labels(earlier) if earlier is not None else None
    protected_before = needs_work_before = None
    if before is not None:
        protected_before = sum(1 for label in before.values() if label == PROTECTED)
        needs_work_before = sum(1 for label in before.values() if label in NEEDS_WORK)
    return ClientPosture(
        client_id=client_id,
        name=name,
        score_text=format_fixed(result.score),
        score_share=max(0, min(int(result.score), 100)),
        band=result.band,
        insufficient=result.insufficient,
        coverage_percent=percent(result.coverage),
        counts=view.counts,
        change_text=change_words(view.snapshot, earlier),
        evidence=evidence,
        protected_before=protected_before,
        needs_work_before=needs_work_before,
    )


# --- what needs attention -----------------------------------------------------------


@dataclass(frozen=True)
class AttentionItem:
    """One control of one client that is not protected or needs attention."""

    client_id: int
    client_name: str
    control_id: str
    title: str
    label: StatusLabel
    gate: bool
    weight: int
    reasons: tuple[str, ...]

    @property
    def href(self) -> str:
        return f"/clients/{self.client_id}/controls/{self.control_id}"

    @property
    def path(self) -> str:
        """The address without its leading slash; the template writes the slash."""
        return self.href[1:]

    @property
    def why(self) -> str:
        """The reasons beyond the status itself: old evidence, an open exception."""
        return ", ".join(
            reason.lower() for reason in self.reasons if reason != self.label.text
        )


def attention_items(
    client_id: int, name: str, view: ReportView, excepted: Collection[str]
) -> list[AttentionItem]:
    """The ranked findings of one client as dashboard items."""
    return [
        AttentionItem(
            client_id=client_id,
            client_name=name,
            control_id=item.row.control_id,
            title=item.row.title,
            label=item.row.label,
            gate=item.row.gate,
            weight=item.row.weight,
            reasons=flags_of(item.row, item.row.control_id in excepted),
        )
        for item in view.ranked
    ]


def prioritised(items: Iterable[AttentionItem]) -> list[AttentionItem]:
    """Gates first, then what is not protected, then by weight, client and id."""

    def key(item: AttentionItem) -> tuple[int, int, int, str, str]:
        return (
            0 if item.gate else 1,
            URGENCY.get(item.label, 2),
            -item.weight,
            item.client_name,
            item.control_id,
        )

    return sorted(items, key=key)


# --- the breakdown by domain and the evidence sources -------------------------------


@dataclass(frozen=True)
class Segment:
    """One part of a stacked bar: a status, its count, its start and its width."""

    label: StatusLabel
    count: int
    x: str
    width: str


def segments_of(counts: Sequence[tuple[StatusLabel, int]]) -> tuple[Segment, ...]:
    """The segments of a bar 100 units wide, in the order of the counts."""
    total = sum(count for _, count in counts)
    found: list[Segment] = []
    start = Fraction(0)
    for label, count in counts:
        if count == 0 or total == 0:
            continue
        width = Fraction(count * 100, total)
        found.append(
            Segment(label, count, format_fixed(start, 2), format_fixed(width, 2))
        )
        start += width
    return tuple(found)


@dataclass(frozen=True)
class DomainBar:
    """One domain across every client: the controls by status."""

    code: str
    name: str
    counts: tuple[tuple[StatusLabel, int], ...]

    @property
    def total(self) -> int:
        return sum(count for _, count in self.counts)

    @property
    def segments(self) -> tuple[Segment, ...]:
        return segments_of(self.counts)


def domain_bars(rows: Iterable[DomainRow]) -> list[DomainBar]:
    """The domains of every client added up, in the order of the control library."""
    names: dict[str, str] = {}
    totals: dict[str, dict[StatusLabel, int]] = {}
    for row in rows:
        names.setdefault(row.code, row.name)
        found = totals.setdefault(row.code, dict.fromkeys(COUNTED_LABELS, 0))
        for label, count in row.counts:
            found[label] = found.get(label, 0) + count
    return [
        DomainBar(code, names[code], tuple((label, found[label]) for label in found))
        for code, found in totals.items()
    ]


@dataclass(frozen=True)
class EvidenceSummary:
    """The evidence sources of every client by state."""

    counts: tuple[tuple[StatusLabel, int], ...]

    def of(self, label: StatusLabel) -> int:
        return sum(count for item, count in self.counts if item == label)

    @property
    def to_refresh(self) -> int:
        return self.of(STALE) + self.of(EXPIRED) + self.of(MISSING)

    @property
    def segments(self) -> tuple[Segment, ...]:
        return segments_of(self.counts)


def evidence_summary(rows: Iterable[SourceRow]) -> EvidenceSummary:
    found = dict.fromkeys((CURRENT, STALE, EXPIRED, MISSING), 0)
    for row in rows:
        found[row.state] = found.get(row.state, 0) + 1
    return EvidenceSummary(tuple(found.items()))


# --- the stored reports: points, the weekly series and the trend chart ---------------


@dataclass(frozen=True)
class ReportPoint:
    """One stored report: its score and the counts its labels give.

    `snapshot_id` is the row of the report, so a mark on a chart can open it; 0
    when the point was read without its row (the report page then opens the list).
    """

    client_id: int
    as_of: datetime
    score: Fraction
    band: str
    insufficient: bool
    protected: int
    needs_work: int
    snapshot_id: int = 0

    @property
    def path(self) -> str:
        """The report this point is, without its leading slash; the template
        writes the slash, so every link is visibly same-origin."""
        if self.snapshot_id:
            return f"clients/{self.client_id}/reports/{self.snapshot_id}"
        return f"clients/{self.client_id}/reports"


def point_of(
    client_id: int, snapshot: SnapshotInput, snapshot_id: int = 0
) -> ReportPoint:
    result = score_snapshot(snapshot)
    labels = previous_labels(snapshot).values()
    return ReportPoint(
        client_id=client_id,
        as_of=snapshot.as_of,
        score=result.score,
        band=result.band,
        insufficient=result.insufficient,
        protected=sum(1 for label in labels if label == PROTECTED),
        needs_work=sum(1 for label in labels if label in NEEDS_WORK),
        snapshot_id=snapshot_id,
    )


def report_points(rows: Iterable[Sequence[Any]]) -> list[ReportPoint]:
    """The points of stored snapshot documents, oldest first; a bad one is skipped.

    A row is (client id, document) or (client id, document, snapshot id), as a
    tuple or a row of a query; with the id, the point knows the report it opens.
    """
    points: list[ReportPoint] = []
    for row in rows:
        client_id = int(row[0])
        snapshot_id = int(row[2]) if len(row) > 2 else 0
        try:
            snapshot = parse_snapshot(document_bytes(dict(row[1])))
        except SnapshotError:
            continue
        points.append(point_of(client_id, snapshot, snapshot_id))
    return sorted(points, key=lambda point: (point.as_of, point.client_id))


@dataclass(frozen=True)
class WeekPoint:
    """The book of clients at the end of one week, from the newest report of each."""

    end: datetime
    clients: int
    protected: int | None
    needs_work: int | None


def weekly_series(
    points: Sequence[ReportPoint],
    created: Sequence[datetime],
    now: datetime,
    weeks: int = WEEKS,
) -> list[WeekPoint]:
    """One point per week: the clients that existed and the sums of their newest
    reports at that moment. A week before the first report has no sums."""
    series: list[WeekPoint] = []
    for back in range(weeks - 1, -1, -1):
        end = now - timedelta(days=7 * back)
        latest: dict[int, ReportPoint] = {}
        for point in points:
            if point.as_of <= end:
                latest[point.client_id] = point
        clients = sum(1 for moment in created if moment <= end)
        if latest:
            protected = sum(point.protected for point in latest.values())
            needs_work = sum(point.needs_work for point in latest.values())
            series.append(WeekPoint(end, clients, protected, needs_work))
        else:
            series.append(WeekPoint(end, clients, None, None))
    return series


def spark_points(
    values: Sequence[int | Fraction | None],
    width: int = SPARK_WIDTH,
    height: int = SPARK_HEIGHT,
) -> list[tuple[int, str, str]]:
    """(index, x, y) of every known value on the box of a sparkline; empty below
    two known values, since one point is not a line."""
    known = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(known) < 2:
        return []
    low = min(value for _, value in known)
    high = max(value for _, value in known)
    span = (high - low) or 1
    steps = max(len(values) - 1, 1)
    found: list[tuple[int, str, str]] = []
    for index, value in known:
        x = SPARK_PAD + (width - 2 * SPARK_PAD) * index / steps
        y = height - SPARK_PAD - (height - 2 * SPARK_PAD) * float(value - low) / span
        found.append((index, f"{x:.1f}", f"{y:.1f}"))
    return found


def sparkline(
    values: Sequence[int | Fraction | None],
    width: int = SPARK_WIDTH,
    height: int = SPARK_HEIGHT,
) -> str:
    """The points of a polyline through the known values; empty below two."""
    return " ".join(f"{x},{y}" for _, x, y in spark_points(values, width, height))


@dataclass(frozen=True)
class SparkMark:
    """One week on a sparkline: where it sits, its value and the tooltip words."""

    x: str
    y: str
    value: str
    tip: str


def spark_marks(
    values: Sequence[int | Fraction | None],
    weeks: Sequence[WeekPoint],
    what: str,
) -> tuple[SparkMark, ...]:
    """A mark per known week, with the week and the exact value in words."""
    marks: list[SparkMark] = []
    for index, x, y in spark_points(values):
        value = values[index]
        if value is None:
            continue
        end = iso_date(weeks[index].end)
        marks.append(SparkMark(x, y, str(value), f"Week ending {end}\n{value} {what}"))
    return tuple(marks)


@dataclass(frozen=True)
class Mark:
    """One stored report on a trend line: the point to land on, the report it
    opens (a path without its leading slash) and the exact values in words."""

    x: str
    y: str
    day: str
    score: str
    band: str
    path: str
    tip: str


@dataclass(frozen=True)
class TrendLine:
    """The reports of one client as a line, with its label and its numbers."""

    client_id: int
    name: str
    points: str
    last_x: str
    last_y: str
    label_y: str
    dash: str
    rows: tuple[tuple[str, str, str], ...]
    marks: tuple[Mark, ...] = ()
    # The date of the report before the range that the line continues from (it
    # enters the plot at the left edge); empty when the line starts in the range.
    continues_from: str = ""

    @property
    def short_name(self) -> str:
        if len(self.name) <= NAME_LENGTH:
            return self.name
        return self.name[: NAME_LENGTH - 3].rstrip() + "..."


@dataclass(frozen=True)
class ChartSize:
    """The geometry of a trend drawing in SVG units: its box, the margins around
    the plot, how many dates the time axis names, and whether each line is labelled
    at its end. The page draws the chart twice and shows the one that suits the
    width: the wide drawing, whose labels sit at the ends of the lines, and the
    narrow one for a phone, where a 640-unit drawing would shrink to half and its
    labels with it, so the clients are named in a legend under it instead.
    """

    kind: str
    width: int
    height: int
    left: int
    right: int
    top: int
    bottom: int
    dates: int
    labelled: bool


WIDE_CHART = ChartSize(
    "wide",
    CHART_WIDTH,
    CHART_HEIGHT,
    CHART_LEFT,
    CHART_RIGHT,
    CHART_TOP,
    CHART_BOTTOM,
    dates=4,
    labelled=True,
)
NARROW_CHART = ChartSize("narrow", 320, 200, 36, 16, 12, 28, dates=3, labelled=False)


@dataclass(frozen=True)
class TrendChart:
    lines: tuple[TrendLine, ...]
    x_ticks: tuple[tuple[str, str, str], ...]
    y_ticks: tuple[tuple[str, str], ...]
    left: int = CHART_LEFT
    right: int = CHART_WIDTH - CHART_RIGHT
    top: int = CHART_TOP
    bottom: int = CHART_HEIGHT - CHART_BOTTOM
    width: int = CHART_WIDTH
    height: int = CHART_HEIGHT
    kind: str = "wide"
    labelled: bool = True

    @property
    def reports(self) -> int:
        return sum(len(line.rows) for line in self.lines)


@dataclass(frozen=True)
class _Drawn:
    """A line while the chart is laid out, before its label has its place."""

    client_id: int
    last_x: float
    last_y: float
    polyline: str
    dash: str
    rows: tuple[tuple[str, str, str], ...]
    marks: tuple[Mark, ...]
    continues_from: str


def mark_of(point: ReportPoint, name: str, x: float, y: float) -> Mark:
    """The mark of one report, with the words its tooltip and its table row show."""
    day = iso_date(point.as_of)
    score = format_fixed(point.score)
    if point.insufficient:
        words = f"{day}: lower bound {score}, {point.band}"
    else:
        words = f"{day}: score {score}, {point.band}"
    return Mark(
        x=f"{x:.1f}",
        y=f"{y:.1f}",
        day=day,
        score=score,
        band=point.band,
        path=point.path,
        tip=f"{name}\n{words}",
    )


def _chart_x(
    moment: datetime, start: datetime, now: datetime, size: ChartSize = WIDE_CHART
) -> float:
    plot = size.width - size.right - size.left
    share = (moment - start) / (now - start) if now > start else 1.0
    return size.left + plot * max(0.0, min(share, 1.0))


def _chart_y(score: Fraction, size: ChartSize = WIDE_CHART) -> float:
    plot = size.height - size.bottom - size.top
    return size.height - size.bottom - plot * float(score) / 100


def _entering_y(
    earlier: ReportPoint,
    first: ReportPoint,
    start: datetime,
    size: ChartSize = WIDE_CHART,
) -> float:
    """Where the line between two reports crosses the left edge of the plot, the
    instant `start` between `earlier` (before it) and `first` (after it)."""
    share = (start - earlier.as_of) / (first.as_of - earlier.as_of)
    low = _chart_y(earlier.score, size)
    return low + (_chart_y(first.score, size) - low) * share


def _label_places(drawn: Sequence[_Drawn], size: ChartSize) -> dict[int, float]:
    """Where the label of each line goes: at the end of its line, pushed down by
    LABEL_GAP from the label above when two ends are close. A stack that would
    reach past the plot sat on the dates of the time axis (seen with several
    clients at a score of 0), so it is moved up by the excess, keeping its gaps:
    six labels of 18 units fit in the 180 units of the plot."""
    labels: dict[int, float] = {}
    floor = size.top + LABEL_GAP / 2
    for item in sorted(drawn, key=lambda item: item.last_y):
        floor = max(floor, item.last_y)
        labels[item.client_id] = floor
        floor += LABEL_GAP
    ceiling = size.height - size.bottom - LABEL_GAP / 2
    excess = max(labels.values(), default=0.0) - ceiling
    if excess > 0:
        labels = {client_id: y - excess for client_id, y in labels.items()}
    return labels


def _anchor(number: int, count: int) -> str:
    """The first date is written from its tick and the last up to its tick, so
    neither is cut at an edge of the drawing; the others are centred."""
    if number == 0:
        return "start"
    return "end" if number == count - 1 else "middle"


def trend_chart(
    points: Sequence[ReportPoint],
    names: Mapping[int, str],
    now: datetime,
    days: int = HISTORY_DAYS,
    max_lines: int = MAX_TREND_LINES,
    size: ChartSize = WIDE_CHART,
) -> TrendChart:
    """The scores of the last `days` as one line per client, newest clients first.

    The range is `start <= as_of <= now` with `start = now - days`, one point per
    stored report (not per day), in the instants the reports are stored in; a client
    appears when it has a report inside it. A report just before `start` is not
    drawn as a point, but the line of a client that also has a report inside the
    range enters the plot from it: the segment between the two reports is cut at the
    left edge (`continues_from` names the earlier report), so a monthly report
    cadence does not leave a 30 or 7 day chart with a lone dot. Marks, rows and the
    report count stay the reports inside the range only.

    The labels at the ends of the lines are pushed apart so that two clients with
    the same score can both be read; the table under the chart has every number.
    """
    start = now - timedelta(days=days)
    by_client: dict[int, list[ReportPoint]] = {}
    before: dict[int, ReportPoint] = {}
    for point in points:
        if start <= point.as_of <= now:
            by_client.setdefault(point.client_id, []).append(point)
        elif point.as_of < start:
            held = before.get(point.client_id)
            if held is None or point.as_of >= held.as_of:
                before[point.client_id] = point
    newest = sorted(
        by_client, key=lambda client_id: by_client[client_id][-1].as_of, reverse=True
    )
    chosen = sorted(newest[:max_lines], key=lambda client_id: names.get(client_id, ""))
    drawn: list[_Drawn] = []
    for number, client_id in enumerate(chosen):
        series = by_client[client_id]
        pairs = [
            (_chart_x(point.as_of, start, now, size), _chart_y(point.score, size))
            for point in series
        ]
        line = pairs
        continues_from = ""
        earlier = before.get(client_id)
        if earlier is not None and series[0].as_of > start:
            entering = _entering_y(earlier, series[0], start, size)
            line = [(float(size.left), entering), *pairs]
            continues_from = iso_date(earlier.as_of)
        polyline = ""
        if len(line) > 1:
            polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in line)
        rows = tuple(
            (iso_date(point.as_of), format_fixed(point.score), point.band)
            for point in series
        )
        name = names.get(client_id, DELETED_CLIENT)
        marks = tuple(
            mark_of(point, name, x, y)
            for point, (x, y) in zip(series, pairs, strict=True)
        )
        last_x, last_y = pairs[-1]
        dash = DASHES[number % len(DASHES)]
        drawn.append(
            _Drawn(
                client_id, last_x, last_y, polyline, dash, rows, marks, continues_from
            )
        )
    labels = _label_places(drawn, size)
    lines = tuple(
        TrendLine(
            client_id=item.client_id,
            name=names.get(item.client_id, DELETED_CLIENT),
            points=item.polyline,
            last_x=f"{item.last_x:.1f}",
            last_y=f"{item.last_y:.1f}",
            label_y=f"{labels[item.client_id]:.1f}",
            dash=item.dash,
            rows=item.rows,
            marks=item.marks,
            continues_from=item.continues_from,
        )
        for item in drawn
    )
    # The dates divide the span evenly: a whole number of days per step put the
    # middle date of a three-day span at a third of the axis, into the first one.
    steps = max(size.dates - 1, 1)
    span = now - start
    ticks = [start + span * k / steps for k in range(size.dates)]
    x_ticks = tuple(
        (
            f"{_chart_x(moment, start, now, size):.1f}",
            iso_date(moment),
            _anchor(number, len(ticks)),
        )
        for number, moment in enumerate(ticks)
    )
    y_ticks = tuple(
        (f"{_chart_y(Fraction(value), size):.1f}", str(value)) for value in (0, 50, 100)
    )
    return TrendChart(
        lines=lines,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        left=size.left,
        right=size.width - size.right,
        top=size.top,
        bottom=size.height - size.bottom,
        width=size.width,
        height=size.height,
        kind=size.kind,
        labelled=size.labelled,
    )


# --- the stat cards -----------------------------------------------------------------


@dataclass(frozen=True)
class Stat:
    key: str
    label: str
    value: str
    note: str
    change: str
    spark: str
    href: str
    marks: tuple[SparkMark, ...] = ()

    @property
    def spark_label(self) -> str:
        """What the sparkline is, for a screen reader: the weeks and the values."""
        if not self.marks:
            return ""
        values = ", ".join(mark.value for mark in self.marks)
        return f"{self.label}, week by week: {values}"

    @property
    def anchor(self) -> str:
        """The part of Home the number leads to, without the hash; empty otherwise."""
        return self.href[1:] if self.href.startswith("#") else ""

    @property
    def path(self) -> str:
        """The page the number leads to, without the leading slash; empty otherwise."""
        return self.href[1:] if self.href.startswith("/") else ""


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def change_since_reports(postures: Sequence[ClientPosture], what: str) -> str:
    """How a count moved against the last stored report of every client that has one."""
    compared = [item for item in postures if item.protected_before is not None]
    if not compared:
        return "No earlier report to compare with"
    if what == "protected":
        now = sum(item.protected for item in compared)
        then = sum(item.protected_before or 0 for item in compared)
    else:
        now = sum(item.needs_work for item in compared)
        then = sum(item.needs_work_before or 0 for item in compared)
    delta = now - then
    reports = _plural(len(compared), "client", "clients")
    if delta == 0:
        return f"Unchanged since the last reports of {reports}"
    return f"{delta:+d} since the last reports of {reports}"


def stat_cards(
    postures: Sequence[ClientPosture],
    weekly: Sequence[WeekPoint],
    evidence: EvidenceSummary,
) -> list[Stat]:
    """The four numbers at the top of Home, each with its context and its history."""
    with_evidence = sum(1 for item in postures if item.evidence)
    protected = sum(item.protected for item in postures)
    counted = sum(item.counted for item in postures)
    needs_work = sum(item.needs_work for item in postures)
    share = percent(Fraction(protected, counted)) if counted else "0"
    client_weeks = [week.clients for week in weekly]
    protected_weeks = [week.protected for week in weekly]
    work_weeks = [week.needs_work for week in weekly]
    return [
        Stat(
            key="clients",
            label="Clients",
            value=str(len(postures)),
            note=f"{with_evidence} with evidence imported",
            change="",
            spark=sparkline(client_weeks),
            href="/clients",
            marks=spark_marks(client_weeks, weekly, "clients"),
        ),
        Stat(
            key="protected",
            label="Controls protected",
            value=str(protected),
            note=f"of {counted} counted controls ({share}%)",
            change=change_since_reports(postures, "protected"),
            spark=sparkline(protected_weeks),
            href="/clients",
            marks=spark_marks(protected_weeks, weekly, "controls protected"),
        ),
        Stat(
            key="needs-work",
            label="Controls that need work",
            value=str(needs_work),
            note="not protected, or needing attention",
            change=change_since_reports(postures, "needs_work"),
            spark=sparkline(work_weeks),
            href="#needs-attention",
            marks=spark_marks(work_weeks, weekly, "controls that need work"),
        ),
        Stat(
            key="evidence",
            label="Exports to refresh",
            value=str(evidence.to_refresh),
            note=(
                f"{evidence.of(EXPIRED)} expired, {evidence.of(STALE)} stale, "
                f"{evidence.of(MISSING)} never imported"
            ),
            change="",
            spark="",
            href="/clients",
        ),
    ]


# --- the recent changes -------------------------------------------------------------


@dataclass(frozen=True)
class ChangeLine:
    """One entry of the audit trail as the timeline shows it."""

    when: datetime
    ago: str
    actor: str
    words: str
    client_name: str
    href: str

    @property
    def when_text(self) -> str:
        return self.when.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def when_iso(self) -> str:
        return self.when.astimezone(UTC).isoformat()

    @property
    def path(self) -> str:
        """The page without its leading slash (the template writes it); empty: none."""
        return self.href[1:] if self.href.startswith("/") else ""


def ago(moment: datetime, now: datetime) -> str:
    """How long ago, in words a person reads at a glance."""
    seconds = max(int((now - moment).total_seconds()), 0)
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{_plural(minutes, 'minute', 'minutes')} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{_plural(hours, 'hour', 'hours')} ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    return iso_date(moment)


def _client_of(event: AuditEvent) -> int | None:
    found = event.detail.get("client_id")
    if isinstance(found, int) and not isinstance(found, bool):
        return found
    target = event.target_id or ""
    if event.target_type == "client" and target.isdecimal():
        return int(target)
    return None


def _words_of(event: AuditEvent) -> str:
    if event.action == "report.export":
        kind = event.detail.get("kind")
        name = REPORT_NAMES.get(kind, "Report") if isinstance(kind, str) else "Report"
        return f"{name} exported"
    return EVENT_WORDS.get(event.action, event.action.replace(".", " ").capitalize())


def change_lines(
    events: Iterable[AuditEvent],
    client_names: Mapping[int, str],
    usernames: Mapping[int, str],
    now: datetime,
) -> list[ChangeLine]:
    """The audit events as timeline lines, with the client and the person named."""
    lines: list[ChangeLine] = []
    for event in events:
        client_id = _client_of(event)
        name = ""
        href = ""
        if client_id is not None:
            name = client_names.get(client_id) or deleted_client_name(client_id)
            if client_id in client_names and event.action != "client.deleted":
                page = EVENT_PAGES.get(event.action)
                href = f"/clients/{client_id}" + (f"/{page}" if page else "")
        if event.actor_user_id is None:
            actor = SYSTEM_ACTOR
        else:
            actor = usernames.get(event.actor_user_id, UNKNOWN_ACTOR)
        lines.append(
            ChangeLine(
                when=event.occurred_at,
                ago=ago(event.occurred_at, now),
                actor=actor,
                words=_words_of(event),
                client_name=name,
                href=href,
            )
        )
    return lines
