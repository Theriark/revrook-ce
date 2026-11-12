"""The Home page: the dashboard of every client (docs/design-system.md, Dashboard).

Nothing here is stored. Every client is read the way its overview page reads it
(`load_live`, then `view_of` against its last stored report), the stored reports of
the last 90 days give the history, and the audit trail gives the recent changes. A
client whose evidence cannot be read today is listed under a warning instead of
stopping the page.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import count_users
from app.evidence.errors import EvidenceError
from app.evidence.service import list_evidence
from app.models import AppUser, AuditEvent, Client, Fact, Snapshot
from app.posture import load_live, view_of
from app.reports.view import ControlRow, DomainRow, ReportContext, ReportError
from app.snapshots import earlier_bytes
from app.ui.auth import redirect, render
from app.ui.charts import RANGE_DAYS, RANGE_WORDS, read_days
from app.ui.clients import needed_sources
from app.ui.common import (
    FormError,
    library_of,
    problem,
    read_period,
    signed_in_user,
    to_login,
)
from app.ui.dashboard import (
    EVENT_WORDS,
    HISTORY_DAYS,
    MAX_EVENTS,
    MAX_SNAPSHOTS,
    NARROW_CHART,
    AttentionItem,
    ClientPosture,
    attention_items,
    change_lines,
    domain_bars,
    evidence_summary,
    posture_of,
    prioritised,
    report_points,
    stat_cards,
    trend_chart,
    weekly_series,
)
from app.ui.drivers import DRIVERS, portfolio_of
from app.ui.viewmodels import (
    SourceRow,
    read_earlier,
    source_max_ages,
    source_rows,
)
from app.web import clock_of, current_session, session_factory

router = APIRouter()
# Home lists the five most urgent controls; the rest are on the checklists
HOME_ATTENTION = 5
# The company card of the scene names the three most urgent controls of its client
CARD_FOCUS = 3


@dataclass(frozen=True)
class Unread:
    """A client the dashboard could not read today, and why."""

    client_id: int
    name: str
    reason: str


async def active_clients(session: AsyncSession) -> list[tuple[int, str, datetime]]:
    found = await session.execute(
        select(Client.id, Client.name, Client.created_at)
        .where(Client.archived_at.is_(None))
        .order_by(Client.name, Client.id)
    )
    return [(client_id, name, created) for client_id, name, created in found.all()]


async def client_names(session: AsyncSession) -> dict[int, str]:
    """Every client, archived ones included, so an old event still names it."""
    found = await session.execute(select(Client.id, Client.name))
    return {client_id: name for client_id, name in found.all()}


# The facts that say how big a client is: its people in Entra, else its devices
SIZE_FACTS = {
    "entra.summary": "users",
    "intune.summary": "devices",
    "inventory.summary": "devices",
}


async def company_sizes(session: AsyncSession) -> dict[int, int]:
    """How big each client is, for the base of its rook on Home: the people of its
    newest Entra export, else the devices of its newest device export; a client
    with neither has no size (the scene draws it at the smallest base)."""
    newest = await session.execute(
        select(Fact.client_id, Fact.fact_key, Fact.value)
        .where(Fact.fact_key.in_(list(SIZE_FACTS)))
        .distinct(Fact.client_id, Fact.fact_key)
        .order_by(
            Fact.client_id, Fact.fact_key, Fact.captured_at.desc(), Fact.id.desc()
        )
    )
    people: dict[int, int] = {}
    devices: dict[int, int] = {}
    for client_id, key, value in newest:
        count = value.get(SIZE_FACTS[key]) if isinstance(value, dict) else None
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            continue
        if key == "entra.summary":
            people[client_id] = count
        else:
            devices[client_id] = max(devices.get(client_id, 0), count)
    return {**devices, **people}


async def usernames(session: AsyncSession) -> dict[int, str]:
    found = await session.execute(select(AppUser.id, AppUser.username))
    return {user_id: name for user_id, name in found.all()}


async def recent_snapshots(
    session: AsyncSession, since: datetime
) -> list[tuple[int, dict[str, Any], int]]:
    """The stored reports of the active clients since `since`, newest first, each
    with the id of its row so a mark on a chart can open it."""
    found = await session.execute(
        select(Snapshot.client_id, Snapshot.inputs, Snapshot.id)
        .join(Client, Client.id == Snapshot.client_id)
        .where(Client.archived_at.is_(None), Snapshot.as_of >= since)
        .order_by(Snapshot.as_of.desc(), Snapshot.id.desc())
        .limit(MAX_SNAPSHOTS)
    )
    return [
        (client_id, document, snapshot_id)
        for client_id, document, snapshot_id in found.all()
    ]


async def snapshots_before(
    session: AsyncSession, before: datetime
) -> list[tuple[int, dict[str, Any], int]]:
    """The newest stored report of each active client strictly before `before`:
    the report a trend line enters the range from (see `trend_chart`)."""
    ranked = (
        select(
            Snapshot.client_id.label("client_id"),
            Snapshot.inputs.label("inputs"),
            Snapshot.id.label("snapshot_id"),
            func.row_number()
            .over(
                partition_by=Snapshot.client_id,
                order_by=(Snapshot.as_of.desc(), Snapshot.id.desc()),
            )
            .label("place"),
        )
        .join(Client, Client.id == Snapshot.client_id)
        .where(Client.archived_at.is_(None), Snapshot.as_of < before)
        .subquery()
    )
    found = await session.execute(
        select(ranked.c.client_id, ranked.c.inputs, ranked.c.snapshot_id).where(
            ranked.c.place == 1
        )
    )
    return [
        (client_id, document, snapshot_id)
        for client_id, document, snapshot_id in found.all()
    ]


async def trend_context(request: Request, now: datetime, days: int) -> dict[str, Any]:
    """The trend chart alone, for the range swapped in by the chart script: the
    stored reports of the last `days`, the report before them each line enters
    from, and the names of the clients."""
    since = now - timedelta(days=days)
    async with session_factory(request)() as session:
        points = report_points(
            [
                *await recent_snapshots(session, since),
                *await snapshots_before(session, since),
            ]
        )
        names = await client_names(session)
    return {
        "trend": trend_chart(points, names, now, days=days),
        "trend_narrow": trend_chart(points, names, now, days=days, size=NARROW_CHART),
        "days": days,
        "ranges": [(value, RANGE_WORDS[value]) for value in RANGE_DAYS],
    }


async def recent_events(session: AsyncSession) -> list[AuditEvent]:
    found = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.action.in_(list(EVENT_WORDS)))
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(MAX_EVENTS)
    )
    return list(found.scalars())


@dataclass(frozen=True)
class ClientsToday:
    """Every active client read today, the way its overview reads it: what Home
    shows, and what the companies ring of the Evidence Explorer draws."""

    postures: list[ClientPosture] = field(default_factory=list)
    attention: list[AttentionItem] = field(default_factory=list)
    domain_rows: list[DomainRow] = field(default_factory=list)
    sources: list[SourceRow] = field(default_factory=list)
    unread: list[Unread] = field(default_factory=list)
    created: list[datetime] = field(default_factory=list)
    # Per client, for its company card in a scene: its most urgent controls and
    # how many of its exports are due for a refresh.
    focus: dict[int, list[AttentionItem]] = field(default_factory=dict)
    refresh: dict[int, int] = field(default_factory=dict)
    # Per client, every control of the library with its label today.
    rows: dict[int, tuple[ControlRow, ...]] = field(default_factory=dict)


async def read_clients(
    request: Request, user: AppUser, session: AsyncSession, now: datetime
) -> ClientsToday:
    """Every active client read once (one live evaluation each, `load_live` then
    `view_of` against its last stored report). A client whose evidence cannot be
    read today is listed in `unread` instead of stopping the page."""
    library = library_of(request)
    wanted = needed_sources(request)
    ages = source_max_ages(library)
    start, end = read_period("", "", now.date())
    today = ClientsToday()
    for client_id, name, created_at in await active_clients(session):
        today.created.append(created_at)
        try:
            live = await load_live(session, library, client_id, now)
            earlier = await earlier_bytes(session, client_id)
            evidence = await list_evidence(session, client_id, now)
            context = ReportContext(
                msp_name="",
                client_name=name,
                period_start=start,
                period_end=end,
                prepared_by=user.username,
                generated_on=now.date(),
            )
            view = view_of(live, library, context, earlier)
        except (EvidenceError, ReportError) as error:
            today.unread.append(Unread(client_id, name, str(error)))
            continue
        today.postures.append(
            posture_of(client_id, name, view, read_earlier(earlier), len(evidence))
        )
        excepted = {entry.control_id for entry in live.exceptions}
        items = attention_items(client_id, name, view, excepted)
        today.attention.extend(items)
        today.focus[client_id] = prioritised(items)[:CARD_FOCUS]
        today.domain_rows.extend(view.domains)
        rows = source_rows(evidence, wanted, ages, now)
        today.sources.extend(rows)
        today.refresh[client_id] = evidence_summary(rows).to_refresh
        today.rows[client_id] = tuple(view.rows)
    return today


async def load_board(
    request: Request, user: AppUser, now: datetime, days: int = HISTORY_DAYS
) -> dict[str, Any]:
    """Everything the dashboard shows, read in one database session. `days` is
    the range of the trend chart; the sparklines keep their twelve weeks."""
    async with session_factory(request)() as session:
        today = await read_clients(request, user, session, now)
        since = now - timedelta(days=HISTORY_DAYS)
        points = report_points(await recent_snapshots(session, since))
        # The trend keeps the range chosen: its reports and, per client, the one
        # before them that the line enters from. The sparklines keep `points`.
        window = now - timedelta(days=days)
        trend_points = [point for point in points if point.as_of >= window]
        trend_points += report_points(await snapshots_before(session, window))
        names = await client_names(session)
        events = await recent_events(session)
        users = await usernames(session)
        sizes = await company_sizes(session)
    postures = today.postures
    weekly = weekly_series(points, today.created, now)
    ranked = prioritised(today.attention)
    return {
        "clients": postures,
        "sizes": sizes,
        "with_evidence": sum(1 for item in postures if item.evidence),
        # What moves the score, over the clients with evidence: a client without
        # any is all "not checked" and would only say that nothing is imported.
        "portfolio": portfolio_of(item.drivers for item in postures if item.evidence),
        "drivers": DRIVERS,
        "unread": today.unread,
        "stats": stat_cards(postures, weekly, evidence_summary(today.sources)),
        "attention": ranked[:HOME_ATTENTION],
        "attention_total": len(today.attention),
        # The company card of each client in the scene.
        "card_focus": today.focus,
        "card_refresh": today.refresh,
        "trend": trend_chart(trend_points, names, now, days=days),
        "trend_narrow": trend_chart(
            trend_points, names, now, days=days, size=NARROW_CHART
        ),
        "domains": domain_bars(today.domain_rows),
        "changes": change_lines(events, names, users, now),
        "days": days,
        "ranges": [(value, RANGE_WORDS[value]) for value in RANGE_DAYS],
    }


@router.get("/")
async def home(request: Request, days: str = "") -> Response:
    """Home: setup first, then sign-in, then the dashboard. `days` is the range
    of the trend chart (7, 30 or 90), the way the chart's own form asks for it
    without script; a value that is not known is refused with a 422."""
    async with session_factory(request)() as db:
        if await count_users(db) == 0:
            return redirect("/setup")
    user = await signed_in_user(request)
    if user is None:
        return to_login(request)
    try:
        chosen = read_days(days)
    except FormError as error:
        return problem(request, user, error.status_code, str(error))
    board = await load_board(request, user, clock_of(request)(), chosen)
    context: dict[str, Any] = {"title": "Home", "nav": "home", "user": user, **board}
    return render(request, "home.html", context, current_session(request))
