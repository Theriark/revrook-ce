"""The Home page: the dashboard of every client (docs/design-system.md, Dashboard).

Nothing here is stored. Every client is read the way its overview page reads it
(`load_live`, then `view_of` against its last stored report), the stored reports of
the last 90 days give the history, and the audit trail gives the recent changes. A
client whose evidence cannot be read today is listed under a warning instead of
stopping the page.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import count_users
from app.evidence.errors import EvidenceError
from app.evidence.service import list_evidence
from app.models import AppUser, AuditEvent, Client, Snapshot
from app.posture import load_live, view_of
from app.reports.view import DomainRow, ReportContext, ReportError
from app.snapshots import earlier_bytes
from app.ui.auth import redirect, render
from app.ui.clients import needed_sources
from app.ui.common import library_of, read_period, signed_in_user, to_login
from app.ui.dashboard import (
    EVENT_WORDS,
    HISTORY_DAYS,
    MAX_ATTENTION,
    MAX_EVENTS,
    MAX_SNAPSHOTS,
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
from app.ui.viewmodels import SourceRow, read_earlier, source_rows
from app.web import clock_of, current_session, session_factory

router = APIRouter()


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


async def usernames(session: AsyncSession) -> dict[int, str]:
    found = await session.execute(select(AppUser.id, AppUser.username))
    return {user_id: name for user_id, name in found.all()}


async def recent_snapshots(
    session: AsyncSession, since: datetime
) -> list[tuple[int, dict[str, Any]]]:
    """The stored reports of the active clients since `since`, newest first."""
    found = await session.execute(
        select(Snapshot.client_id, Snapshot.inputs)
        .join(Client, Client.id == Snapshot.client_id)
        .where(Client.archived_at.is_(None), Snapshot.as_of >= since)
        .order_by(Snapshot.as_of.desc(), Snapshot.id.desc())
        .limit(MAX_SNAPSHOTS)
    )
    return [(client_id, document) for client_id, document in found.all()]


async def recent_events(session: AsyncSession) -> list[AuditEvent]:
    found = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.action.in_(list(EVENT_WORDS)))
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(MAX_EVENTS)
    )
    return list(found.scalars())


async def load_board(request: Request, user: AppUser, now: datetime) -> dict[str, Any]:
    """Everything the dashboard shows, read in one database session."""
    library = library_of(request)
    wanted = needed_sources(request)
    start, end = read_period("", "", now.date())
    postures: list[ClientPosture] = []
    attention: list[AttentionItem] = []
    domain_rows: list[DomainRow] = []
    sources: list[SourceRow] = []
    unread: list[Unread] = []
    created: list[datetime] = []
    async with session_factory(request)() as session:
        for client_id, name, created_at in await active_clients(session):
            created.append(created_at)
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
                unread.append(Unread(client_id, name, str(error)))
                continue
            postures.append(
                posture_of(client_id, name, view, read_earlier(earlier), len(evidence))
            )
            excepted = {entry.control_id for entry in live.exceptions}
            attention.extend(attention_items(client_id, name, view, excepted))
            domain_rows.extend(view.domains)
            sources.extend(source_rows(evidence, wanted))
        since = now - timedelta(days=HISTORY_DAYS)
        points = report_points(await recent_snapshots(session, since))
        names = await client_names(session)
        events = await recent_events(session)
        users = await usernames(session)
    weekly = weekly_series(points, created, now)
    return {
        "clients": postures,
        "with_evidence": sum(1 for item in postures if item.evidence),
        "unread": unread,
        "stats": stat_cards(postures, weekly, evidence_summary(sources)),
        "attention": prioritised(attention)[:MAX_ATTENTION],
        "attention_total": len(attention),
        "trend": trend_chart(points, names, now),
        "domains": domain_bars(domain_rows),
        "changes": change_lines(events, names, users, now),
        "history_days": HISTORY_DAYS,
    }


@router.get("/")
async def home(request: Request) -> Response:
    """Home: setup first, then sign-in, then the dashboard."""
    async with session_factory(request)() as db:
        if await count_users(db) == 0:
            return redirect("/setup")
    user = await signed_in_user(request)
    if user is None:
        return to_login(request)
    board = await load_board(request, user, clock_of(request)())
    context: dict[str, Any] = {"title": "Home", "nav": "home", "user": user, **board}
    return render(request, "home.html", context, current_session(request))
