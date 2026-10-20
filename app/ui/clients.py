"""The client pages (phase 9): list, overview, checklist, control, exceptions, evidence.

The overview, the checklist and the control page show the client as it is today: the
newest export of every source, run through the check engine, with the report's own
wording and status labels. Nothing on them is stored. A snapshot is stored only when a
report is made (app/ui/reports.py). The list reads the newest stored snapshot of each
client for its posture (app/ui/clientlist.py) and runs no check.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.checks.library import Control
from app.checks.model import ControlResult
from app.clients import create_client
from app.drafts import load_draft, save_finding
from app.evidence.errors import ClientNotFoundError, ItemNotFoundError
from app.evidence.locking import lock_client
from app.evidence.service import EvidenceView, list_evidence
from app.exceptions import ExceptionEntry, exception_problems, is_overdue
from app.models import (
    AppUser,
    AuditEvent,
    Client,
    EvidenceItem,
    ExceptionRecord,
    Snapshot,
)
from app.posture import LiveClient, load_live, view_of
from app.reports.completeness import MAX_SHORT, MAX_TEXT
from app.reports.view import ControlRow, Finding, ReportContext, ReportView, iso_date
from app.snapshots import earlier_bytes
from app.sources import source_name
from app.textcheck import control_character, normalise_breaks
from app.ui.auth import redirect
from app.ui.clientlist import (
    FILTERS,
    NO_EVIDENCE,
    ClientCard,
    ListQuery,
    filter_counts,
    last_reports,
    paginate,
    read_query,
    select_rows,
)
from app.ui.common import (
    ControlIdPath,
    FormError,
    RowId,
    guarded,
    is_htmx,
    library_of,
    page,
    parse_day,
    read_period,
    sentence,
)
from app.ui.dashboard import (
    EVENT_WORDS,
    MAX_ATTENTION,
    MAX_EVENTS,
    attention_items,
    change_lines,
    posture_of,
    segments_of,
)
from app.ui.overview import domain_lines
from app.ui.viewmodels import (
    STATE_OF_FRESHNESS,
    checklist_rows,
    coverage_text,
    evidence_facts,
    only_flagged,
    read_earlier,
    reason_text,
    refresh_list,
    source_rows,
)
from app.web import cipher_of, clock_of, session_factory

router = APIRouter()
SHOW_CHOICES = ("all", "flagged")
MAX_REVIEW_YEARS = 5
NO_SUCH_CONTROL = "There is no such control."


@dataclass(frozen=True)
class Loaded:
    """A client as it is today, ready for a page."""

    live: LiveClient
    view: ReportView
    earlier: bytes | None
    evidence: list[EvidenceView]


async def newest_snapshots(session: AsyncSession) -> list[tuple[int, dict[str, Any]]]:
    """The newest stored snapshot document of every active client."""
    found = await session.execute(
        select(Snapshot.client_id, Snapshot.inputs)
        .join(Client, Client.id == Snapshot.client_id)
        .where(Client.archived_at.is_(None))
        .distinct(Snapshot.client_id)
        .order_by(Snapshot.client_id, Snapshot.as_of.desc(), Snapshot.id.desc())
    )
    return [(client_id, document) for client_id, document in found.all()]


async def client_cards(request: Request, now: datetime) -> list[ClientCard]:
    """Every client with its exports, the date of the newest and its last report."""
    async with session_factory(request)() as session:
        rows = await session.execute(
            select(
                Client.id,
                Client.name,
                func.count(EvidenceItem.id),
                func.max(EvidenceItem.captured_at),
            )
            .select_from(Client)
            .outerjoin(EvidenceItem, EvidenceItem.client_id == Client.id)
            .where(Client.archived_at.is_(None))
            .group_by(Client.id, Client.name)
            .order_by(Client.name, Client.id)
        )
        lines = rows.all()
        reports = last_reports(await newest_snapshots(session))
    cards: list[ClientCard] = []
    for client_id, name, count, newest in lines:
        days = None if newest is None else (now - newest).days
        cards.append(
            ClientCard(client_id, name, count, newest, days, reports.get(client_id))
        )
    return cards


async def clients_response(
    request: Request,
    user: AppUser,
    errors: list[str],
    name: str,
    status_code: int = 200,
    query: ListQuery | None = None,
) -> Response:
    query = query or ListQuery()
    cards = await client_cards(request, clock_of(request)())
    shown = paginate(select_rows(cards, query), query.page)
    counts = filter_counts(cards, query)
    context: dict[str, Any] = {
        "title": "Clients",
        "nav": "clients",
        "rows": shown.items,
        "page": shown,
        "query": query,
        "filters": [(key, label, counts[key]) for key, label in FILTERS],
        "total": len(cards),
        "no_evidence": NO_EVIDENCE,
        "errors": errors,
        "name": name,
    }
    return page(request, "clients.html", user, context, status_code)


@router.get("/clients")
async def clients_page(
    request: Request,
    q: str = "",
    show: str = "all",
    sort: str = "name",
    order: str = "asc",
    density: str = "comfortable",
    page: str = "1",
) -> Response:
    async def handle(user: AppUser) -> Response:
        query = read_query(q, show, sort, order, density, page)
        return await clients_response(request, user, [], "", query=query)

    return await guarded(request, handle)


@router.post("/clients")
async def clients_create(
    request: Request, name: Annotated[str, Form()] = ""
) -> Response:
    async def handle(user: AppUser) -> Response:
        try:
            async with session_factory(request)() as session, session.begin():
                client = await create_client(
                    session, cipher_of(request), name, actor_user_id=user.id
                )
        except ValueError as error:
            errors = [sentence(str(error))]
            return await clients_response(request, user, errors, name, 422)
        return redirect(f"/clients/{client.id}")

    return await guarded(request, handle)


def needed_sources(request: Request) -> list[str]:
    """The sources that a control reads and that an importer exists for."""
    importers = set(request.app.state.importers.source_codes())
    wanted = {target.adapter for target in library_of(request).field_map.values()}
    return sorted(wanted & importers)


async def load_client(
    request: Request, user: AppUser, client_id: int, start: date, end: date
) -> Loaded:
    """The client today: check results, the report view and the stored evidence."""
    library = library_of(request)
    now = clock_of(request)()
    async with session_factory(request)() as session:
        live = await load_live(session, library, client_id, now)
        earlier = await earlier_bytes(session, client_id)
        evidence = await list_evidence(session, client_id, now)
    context = ReportContext(
        msp_name="",
        client_name=live.name,
        period_start=start,
        period_end=end,
        prepared_by=user.username,
        generated_on=now.date(),
    )
    return Loaded(live, view_of(live, library, context, earlier), earlier, evidence)


def client_context(loaded: Loaded, section: str, title: str) -> dict[str, Any]:
    """What every page of one client has in common."""
    return {
        "title": f"{title} - {loaded.live.name}",
        "nav": "clients",
        "client_id": loaded.live.client_id,
        "client_name": loaded.live.name,
        "section": section,
    }


async def client_events(session: AsyncSession, client_id: int) -> list[AuditEvent]:
    """The newest audit events that changed this client, its evidence or reports."""
    named = func.jsonb_extract_path_text(AuditEvent.detail, "client_id") == str(
        client_id
    )
    targeted = and_(
        AuditEvent.target_type == "client", AuditEvent.target_id == str(client_id)
    )
    found = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.action.in_(list(EVENT_WORDS)), or_(named, targeted))
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(MAX_EVENTS)
    )
    return list(found.scalars())


async def actor_names(session: AsyncSession) -> dict[int, str]:
    found = await session.execute(select(AppUser.id, AppUser.username))
    return {user_id: username for user_id, username in found.all()}


@router.get("/clients/{client_id}")
async def overview(
    request: Request,
    client_id: RowId,
    period_start: str = "",
    period_end: str = "",
) -> Response:
    async def handle(user: AppUser) -> Response:
        now = clock_of(request)()
        start, end = read_period(period_start.strip(), period_end.strip(), now.date())
        loaded = await load_client(request, user, client_id, start, end)
        rows = source_rows(loaded.evidence, needed_sources(request))
        name = loaded.live.name
        excepted = {entry.control_id for entry in loaded.live.exceptions}
        attention = attention_items(client_id, name, loaded.view, excepted)
        async with session_factory(request)() as session:
            events = await client_events(session, client_id)
            users = await actor_names(session)
        context = client_context(loaded, "overview", "Overview")
        context.update(
            view=loaded.view,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            sources=rows,
            refresh=refresh_list(rows),
            posture=posture_of(
                client_id,
                name,
                loaded.view,
                read_earlier(loaded.earlier),
                len(loaded.evidence),
            ),
            status_segments=segments_of(loaded.view.counts),
            domains=domain_lines(loaded.view.domains),
            attention=attention[:MAX_ATTENTION],
            attention_total=len(attention),
            changes=change_lines(events, {client_id: name}, users, now),
            # Paths without their leading slash: the template writes the slash, so
            # every link in a template is visibly same-origin.
            client_actions=[
                {
                    "path": f"clients/{client_id}/checklist?show=flagged",
                    "text": "Review flagged controls",
                    "primary": False,
                },
                {
                    "path": (
                        f"clients/{client_id}/reports"
                        f"?period_start={start.isoformat()}"
                        f"&period_end={end.isoformat()}"
                    ),
                    "text": "Prepare a report",
                    "primary": True,
                },
            ],
        )
        return page(request, "client_overview.html", user, context)

    return await guarded(request, handle)


@router.get("/clients/{client_id}/checklist")
async def checklist(request: Request, client_id: RowId, show: str = "all") -> Response:
    async def handle(user: AppUser) -> Response:
        if show not in SHOW_CHOICES:
            raise FormError("Show must be all or flagged.")
        start, end = read_period("", "", clock_of(request)().date())
        loaded = await load_client(request, user, client_id, start, end)
        async with session_factory(request)() as session:
            draft = await load_draft(session, client_id)
        excepted = {entry.control_id for entry in loaded.live.exceptions}
        rows = checklist_rows(
            loaded.view,
            loaded.live.results,
            read_earlier(loaded.earlier),
            draft.owners,
            excepted,
        )
        flagged = only_flagged(rows)
        context = client_context(loaded, "checklist", "Checklist")
        context.update(
            rows=flagged if show == "flagged" else rows,
            total=len(rows),
            flagged_total=len(flagged),
            show=show,
            has_earlier=loaded.earlier is not None,
        )
        return page(request, "checklist.html", user, context)

    return await guarded(request, handle)


def suggested_sentence(row: ControlRow) -> str:
    """A plain sentence to start from, made from the status and the evidence."""
    base = f"{row.title.rstrip('.')}: {row.label.text.lower()}."
    if row.evidence_at is None:
        return f"{base} No dated evidence was available at the pack date."
    kind = row.assurance.lower()
    return f"{base} The evidence is dated {iso_date(row.evidence_at)} ({kind})."


def control_of(request: Request, control_id: str) -> Control:
    """The control of the library with this id; FormError (404) when there is none."""
    for control in library_of(request).controls:
        if control.id == control_id:
            return control
    raise FormError(NO_SUCH_CONTROL, 404)


@router.get("/clients/{client_id}/controls/{control_id}")
async def control_page(
    request: Request, client_id: RowId, control_id: ControlIdPath
) -> Response:
    async def handle(user: AppUser) -> Response:
        control = control_of(request, control_id)
        now = clock_of(request)()
        start, end = read_period("", "", now.date())
        loaded = await load_client(request, user, client_id, start, end)
        async with session_factory(request)() as session:
            draft = await load_draft(session, client_id)
        row = next(item for item in loaded.view.rows if item.control_id == control_id)
        result: ControlResult = loaded.live.results[control_id]
        notes = [
            (entry, is_overdue(entry, now))
            for entry in loaded.live.exceptions
            if entry.control_id == control_id
        ]
        context = client_context(loaded, "checklist", control.id)
        context.update(
            control=control,
            row=row,
            result=result,
            finding=draft.findings.get(control_id, Finding()),
            exceptions=notes,
            suggestion=suggested_sentence(row),
            reason=reason_text(result.reason),
            coverage=coverage_text(result),
        )
        return page(request, "control.html", user, context)

    return await guarded(request, handle)


@router.post("/clients/{client_id}/controls/{control_id}/note")
async def control_note(
    request: Request,
    client_id: RowId,
    control_id: ControlIdPath,
    did: Annotated[str, Form()] = "",
    recommend: Annotated[str, Form()] = "",
    need: Annotated[str, Form()] = "",
    by_when: Annotated[str, Form()] = "",
) -> Response:
    """Autosave of the notes of one control (htmx posts here as the person types)."""

    async def handle(user: AppUser) -> Response:
        control_of(request, control_id)
        note = Finding(did=did, recommend=recommend, need=need, by_when=by_when)
        async with session_factory(request)() as session, session.begin():
            saved = await save_finding(
                session,
                client_id,
                control_id,
                note,
                user_id=user.id,
                now=clock_of(request)(),
            )
        if not is_htmx(request):
            return redirect(f"/clients/{client_id}/controls/{control_id}")
        stamp = saved.astimezone(UTC).strftime("%H:%M:%S")
        return HTMLResponse(
            f'<span role="status">Saved at {stamp} UTC.</span>',
            headers={"Cache-Control": "no-store"},
        )

    return await guarded(request, handle)


@dataclass(frozen=True)
class ExceptionLine:
    """One row of the exceptions register."""

    id: int
    control_id: str
    title: str
    owner: str
    reason: str
    compensating_control: str | None
    review_date: date
    overdue: bool
    closed: bool


async def exception_lines(
    request: Request, session: AsyncSession, client_id: int, today: date
) -> list[ExceptionLine]:
    if await session.get(Client, client_id) is None:
        raise ClientNotFoundError("There is no client with this id.")
    titles = {control.id: control.title for control in library_of(request).controls}
    rows = await session.execute(
        select(ExceptionRecord)
        .where(ExceptionRecord.client_id == client_id)
        .order_by(
            ExceptionRecord.closed_at.is_not(None),
            ExceptionRecord.review_date,
            ExceptionRecord.id,
        )
    )
    lines: list[ExceptionLine] = []
    for row in rows.scalars():
        closed = row.closed_at is not None
        lines.append(
            ExceptionLine(
                id=row.id,
                control_id=row.control_id,
                title=titles.get(row.control_id, row.control_id),
                owner=row.owner,
                reason=row.reason,
                compensating_control=row.compensating_control,
                review_date=row.review_date,
                overdue=not closed and row.review_date < today,
                closed=closed,
            )
        )
    return lines


async def exceptions_response(
    request: Request,
    user: AppUser,
    client_id: int,
    errors: list[str],
    form: dict[str, str],
    status_code: int = 200,
) -> Response:
    now = clock_of(request)()
    async with session_factory(request)() as session:
        lines = await exception_lines(request, session, client_id, now.date())
        client = await session.get(Client, client_id)
    assert client is not None
    controls = [(item.id, item.title) for item in library_of(request).controls]
    context: dict[str, Any] = {
        "title": f"Exceptions - {client.name}",
        "nav": "clients",
        "client_id": client_id,
        "client_name": client.name,
        "section": "exceptions",
        "rows": lines,
        "controls": controls,
        "errors": errors,
        "form": form,
    }
    return page(request, "exceptions.html", user, context, status_code)


@router.get("/clients/{client_id}/exceptions")
async def exceptions_page(request: Request, client_id: RowId) -> Response:
    async def handle(user: AppUser) -> Response:
        return await exceptions_response(request, user, client_id, [], {})

    return await guarded(request, handle)


def text_problems(label: str, value: str, limit: int) -> list[str]:
    if len(value) > limit:
        return [f"{label} is longer than {limit} characters."]
    if control_character(value, allow_breaks=True) is not None:
        return [f"{label} contains a control character."]
    return []


@router.post("/clients/{client_id}/exceptions")
async def exceptions_add(
    request: Request,
    client_id: RowId,
    control_id: Annotated[str, Form()] = "",
    owner: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
    compensating_control: Annotated[str, Form()] = "",
    review_date: Annotated[str, Form()] = "",
) -> Response:
    async def handle(user: AppUser) -> Response:
        now = clock_of(request)()
        form = {
            "control_id": control_id.strip(),
            "owner": owner.strip(),
            "reason": normalise_breaks(reason).strip(),
            "compensating_control": normalise_breaks(compensating_control).strip(),
            "review_date": review_date.strip(),
        }
        problems: list[str] = []
        if form["control_id"] not in {c.id for c in library_of(request).controls}:
            problems.append("Choose one of the controls.")
        problems += text_problems("The owner", form["owner"], MAX_SHORT)
        problems += text_problems("The reason", form["reason"], MAX_TEXT)
        compensating = form["compensating_control"]
        problems += text_problems("The compensating control", compensating, MAX_TEXT)
        review: date | None = None
        try:
            review = parse_day(form["review_date"], "The review date")
        except FormError as error:
            problems.append(str(error))
        if review is not None:
            limit = now.date() + timedelta(days=366 * MAX_REVIEW_YEARS)
            if review > limit:
                problems.append("The review date is more than five years away.")
            else:
                entry = ExceptionEntry(
                    form["control_id"],
                    form["owner"],
                    form["reason"],
                    compensating or None,
                    review,
                )
                problems += [sentence(item) for item in exception_problems(entry)]
        if problems:
            return await exceptions_response(
                request, user, client_id, problems, form, 422
            )
        async with session_factory(request)() as session, session.begin():
            await lock_client(session, client_id)
            record = ExceptionRecord(
                client_id=client_id,
                control_id=form["control_id"],
                owner=form["owner"],
                reason=form["reason"],
                compensating_control=compensating or None,
                review_date=parse_day(form["review_date"], "The review date"),
            )
            session.add(record)
            await session.flush()
            add_audit_event(
                session,
                "exception.added",
                actor_user_id=user.id,
                target_type="exception_record",
                target_id=record.id,
                detail={"client_id": client_id, "control_id": record.control_id},
            )
        return redirect(f"/clients/{client_id}/exceptions")

    return await guarded(request, handle)


@router.post("/clients/{client_id}/exceptions/{exception_id}/close")
async def exceptions_close(
    request: Request, client_id: RowId, exception_id: RowId
) -> Response:
    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session, session.begin():
            await lock_client(session, client_id)
            record = await session.get(ExceptionRecord, exception_id)
            if record is None or record.client_id != client_id:
                raise ItemNotFoundError("There is no such exception for this client.")
            if record.closed_at is None:
                record.closed_at = clock_of(request)()
                add_audit_event(
                    session,
                    "exception.closed",
                    actor_user_id=user.id,
                    target_type="exception_record",
                    target_id=record.id,
                    detail={"client_id": client_id},
                )
        return redirect(f"/clients/{client_id}/exceptions")

    return await guarded(request, handle)


@router.get("/clients/{client_id}/evidence")
async def evidence_page(request: Request, client_id: RowId) -> Response:
    async def handle(user: AppUser) -> Response:
        now = clock_of(request)()
        async with session_factory(request)() as session:
            client = await session.get(Client, client_id)
            if client is None:
                raise ClientNotFoundError("There is no client with this id.")
            views = await list_evidence(session, client_id, now)
        rows = source_rows(views, needed_sources(request))
        items = [
            (view, STATE_OF_FRESHNESS[view.freshness], source_name(view.source_code))
            for view in views
        ]
        context: dict[str, Any] = {
            "title": f"Evidence and imports - {client.name}",
            "nav": "clients",
            "client_id": client_id,
            "client_name": client.name,
            "section": "evidence",
            "sources": rows,
            "refresh": refresh_list(rows),
            "items": items,
            "facts": evidence_facts(rows, views),
            "client_actions": [
                {
                    "path": "imports/profile-editor",
                    "text": "Import an export",
                    "primary": True,
                },
            ],
        }
        return page(request, "evidence_imports.html", user, context)

    return await guarded(request, handle)
