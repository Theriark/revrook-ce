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
LABEL_GAP = 14
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
    """One stored report: its score and the counts its labels give."""

    client_id: int
    as_of: datetime
    score: Fraction
    band: str
    insufficient: bool
    protected: int
    needs_work: int


def point_of(client_id: int, snapshot: SnapshotInput) -> ReportPoint:
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
    )


def report_points(rows: Iterable[tuple[int, Mapping[str, Any]]]) -> list[ReportPoint]:
    """The points of stored snapshot documents, oldest first; a bad one is skipped."""
    points: list[ReportPoint] = []
    for client_id, document in rows:
        try:
            snapshot = parse_snapshot(document_bytes(dict(document)))
        except SnapshotError:
            continue
        points.append(point_of(client_id, snapshot))
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


def sparkline(
    values: Sequence[int | Fraction | None],
    width: int = SPARK_WIDTH,
    height: int = SPARK_HEIGHT,
) -> str:
    """The points of a polyline through the known values; empty below two."""
    known = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(known) < 2:
        return ""
    low = min(value for _, value in known)
    high = max(value for _, value in known)
    span = (high - low) or 1
    steps = max(len(values) - 1, 1)
    parts: list[str] = []
    for index, value in known:
        x = SPARK_PAD + (width - 2 * SPARK_PAD) * index / steps
        y = height - SPARK_PAD - (height - 2 * SPARK_PAD) * float(value - low) / span
        parts.append(f"{x:.1f},{y:.1f}")
    return " ".join(parts)


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

    @property
    def short_name(self) -> str:
        if len(self.name) <= NAME_LENGTH:
            return self.name
        return self.name[: NAME_LENGTH - 3].rstrip() + "..."


@dataclass(frozen=True)
class TrendChart:
    lines: tuple[TrendLine, ...]
    x_ticks: tuple[tuple[str, str], ...]
    y_ticks: tuple[tuple[str, str], ...]
    left: int = CHART_LEFT
    right: int = CHART_WIDTH - CHART_RIGHT
    top: int = CHART_TOP
    bottom: int = CHART_HEIGHT - CHART_BOTTOM
    width: int = CHART_WIDTH
    height: int = CHART_HEIGHT

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


def _chart_x(moment: datetime, start: datetime, now: datetime) -> float:
    plot = CHART_WIDTH - CHART_RIGHT - CHART_LEFT
    share = (moment - start) / (now - start) if now > start else 1.0
    return CHART_LEFT + plot * max(0.0, min(share, 1.0))


def _chart_y(score: Fraction) -> float:
    plot = CHART_HEIGHT - CHART_BOTTOM - CHART_TOP
    return CHART_HEIGHT - CHART_BOTTOM - plot * float(score) / 100


def trend_chart(
    points: Sequence[ReportPoint],
    names: Mapping[int, str],
    now: datetime,
    days: int = HISTORY_DAYS,
    max_lines: int = MAX_TREND_LINES,
) -> TrendChart:
    """The scores of the last `days` as one line per client, newest clients first.

    The labels at the ends of the lines are pushed apart so that two clients with
    the same score can both be read; the table under the chart has every number.
    """
    start = now - timedelta(days=days)
    by_client: dict[int, list[ReportPoint]] = {}
    for point in points:
        if start <= point.as_of <= now:
            by_client.setdefault(point.client_id, []).append(point)
    newest = sorted(
        by_client, key=lambda client_id: by_client[client_id][-1].as_of, reverse=True
    )
    chosen = sorted(newest[:max_lines], key=lambda client_id: names.get(client_id, ""))
    drawn: list[_Drawn] = []
    for number, client_id in enumerate(chosen):
        series = by_client[client_id]
        pairs = [
            (_chart_x(point.as_of, start, now), _chart_y(point.score))
            for point in series
        ]
        polyline = ""
        if len(pairs) > 1:
            polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in pairs)
        rows = tuple(
            (iso_date(point.as_of), format_fixed(point.score), point.band)
            for point in series
        )
        last_x, last_y = pairs[-1]
        dash = DASHES[number % len(DASHES)]
        drawn.append(_Drawn(client_id, last_x, last_y, polyline, dash, rows))
    labels: dict[int, float] = {}
    floor = CHART_TOP + LABEL_GAP / 2
    for item in sorted(drawn, key=lambda item: item.last_y):
        floor = max(floor, item.last_y)
        labels[item.client_id] = floor
        floor += LABEL_GAP
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
        )
        for item in drawn
    )
    ticks = [now - timedelta(days=back) for back in (days, 2 * days // 3, days // 3, 0)]
    x_ticks = tuple(
        (f"{_chart_x(moment, start, now):.1f}", iso_date(moment)) for moment in ticks
    )
    y_ticks = tuple(
        (f"{_chart_y(Fraction(value)):.1f}", str(value)) for value in (0, 50, 100)
    )
    return TrendChart(lines=lines, x_ticks=x_ticks, y_ticks=y_ticks)


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
    return [
        Stat(
            key="clients",
            label="Clients",
            value=str(len(postures)),
            note=f"{with_evidence} with evidence imported",
            change="",
            spark=sparkline([week.clients for week in weekly]),
            href="/clients",
        ),
        Stat(
            key="protected",
            label="Controls protected",
            value=str(protected),
            note=f"of {counted} counted controls ({share}%)",
            change=change_since_reports(postures, "protected"),
            spark=sparkline([week.protected for week in weekly]),
            href="/clients",
        ),
        Stat(
            key="needs-work",
            label="Controls that need work",
            value=str(needs_work),
            note="not protected, or needing attention",
            change=change_since_reports(postures, "needs_work"),
            spark=sparkline([week.needs_work for week in weekly]),
            href="#needs-attention",
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
            name = client_names.get(client_id, DELETED_CLIENT)
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
