"""Reports (phase 9): the builder, the preview, the export and the export history.

A report is made from a stored snapshot (`app/snapshots.py`) and the notes of the
draft (`app/drafts.py`). The preview is the HTML of the report itself, served with a
policy of its own (inline styles, nothing else), because the report carries its
stylesheet inside the file. An export goes through `export_report`: the completeness
check, an immutable copy under its SHA-256 and one row of history. A download reads
that copy back and checks it against its hash, for the client named in the address.
"""

from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.drafts import load_draft, save_details
from app.evidence.errors import ClientNotFoundError
from app.evidence.locking import lock_client
from app.models import AppUser, Client, EvidenceItem
from app.posture import load_live, open_exceptions, view_from
from app.preferences import get_msp_name
from app.reports.completeness import completeness_problems
from app.reports.export import ExportRecord, export_report, list_exports, read_export
from app.reports.render import INSURANCE, KINDS, QBR, REPORT_NAMES, render_report
from app.reports.topics import TOPIC_KEYS, TOPICS, Topic
from app.reports.view import ReportContext, ReportError, ReportView
from app.scoring.snapshot import SnapshotError, parse_snapshot
from app.snapshots import earlier_bytes, list_snapshots, load_snapshot, store_snapshot
from app.sources import source_name
from app.ui.auth import redirect
from app.ui.common import (
    FormError,
    RowId,
    guarded,
    is_htmx,
    library_of,
    page,
    read_period,
)
from app.web import clock_of, files_of, session_factory

router = APIRouter()
PREVIEW_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
NO_SUCH_REPORT = "There is no such report."
KIND_LIST = [(QBR, REPORT_NAMES[QBR]), (INSURANCE, REPORT_NAMES[INSURANCE])]


def check_kind(kind: str) -> str:
    """The kind of report, or FormError (404) when there is no such report."""
    if kind not in KINDS:
        raise FormError(NO_SUCH_REPORT, 404)
    return kind


async def used_sources(
    session: AsyncSession, client_id: int, evidence_ids: list[int]
) -> tuple[str, ...]:
    """The names of the sources whose evidence a snapshot rests on, sorted."""
    if not evidence_ids:
        return ()
    found = await session.execute(
        select(EvidenceItem.source_code)
        .where(
            EvidenceItem.client_id == client_id,
            EvidenceItem.id.in_(evidence_ids),
        )
        .distinct()
    )
    return tuple(sorted(source_name(code) for code in found.scalars()))


async def build_report_view(
    request: Request,
    session: AsyncSession,
    user: AppUser,
    client_id: int,
    snapshot_id: int,
) -> ReportView:
    """The view of a stored snapshot with the details the technician has written."""
    client = await session.get(Client, client_id)
    if client is None:
        raise ClientNotFoundError("There is no client with this id.")
    row, data = await load_snapshot(session, client_id, snapshot_id)
    try:
        evidence = parse_snapshot(data).evidence
    except SnapshotError as error:
        raise ReportError(str(error)) from None
    ids = [int(ref.evidence_id) for ref in evidence if ref.evidence_id.isdecimal()]
    draft = await load_draft(session, client_id)
    context = ReportContext(
        msp_name=await get_msp_name(session),
        client_name=client.name,
        period_start=row.period_start,
        period_end=row.period_end,
        prepared_by=draft.prepared_by or user.username,
        generated_on=clock_of(request)().date(),
        data_sources=await used_sources(session, client_id, ids),
        findings=draft.findings,
        next_quarter_plan=draft.plan,
        exceptions=await open_exceptions(session, client_id),
        topic_owners=draft.owners,
        asked_topics=draft.asked,
    )
    previous = await earlier_bytes(session, client_id, row.as_of, row.id)
    return view_from(data, library_of(request), context, previous)


@router.get("/clients/{client_id}/reports")
async def builder_page(
    request: Request,
    client_id: RowId,
    period_start: str = "",
    period_end: str = "",
) -> Response:
    async def handle(user: AppUser) -> Response:
        today = clock_of(request)().date()
        start, end = read_period(period_start.strip(), period_end.strip(), today)
        async with session_factory(request)() as session:
            client = await session.get(Client, client_id)
            if client is None:
                raise ClientNotFoundError("There is no client with this id.")
            draft = await load_draft(session, client_id)
            lines = await list_snapshots(session, client_id)
            msp_name = await get_msp_name(session)
        topics: list[tuple[Topic, str, bool]] = []
        for topic in TOPICS:
            asked = draft.asked is None or topic.key in draft.asked
            topics.append((topic, draft.owners.get(topic.key, ""), asked))
        context: dict[str, Any] = {
            "title": f"Report builder - {client.name}",
            "nav": "clients",
            "client_id": client_id,
            "client_name": client.name,
            "section": "reports",
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "msp_name": msp_name,
            "prepared_by": draft.prepared_by or user.username,
            "plan_text": "\n".join(draft.plan),
            "topics": topics,
            "snapshots": lines,
            "saved_at": draft.saved_at,
        }
        return page(request, "reports.html", user, context)

    return await guarded(request, handle)


@router.post("/clients/{client_id}/reports/details")
async def save_report_details(request: Request, client_id: RowId) -> Response:
    """Autosave of the report details (htmx posts here as the person types)."""

    async def handle(user: AppUser) -> Response:
        form = await request.form(max_fields=100)
        owners: dict[str, str] = {}
        asked: list[str] = []
        for key in TOPIC_KEYS:
            owner = form.get(f"owner-{key}")
            if isinstance(owner, str):
                owners[key] = owner
            if form.get(f"ask-{key}") is not None:
                asked.append(key)
        plan = form.get("plan")
        preparer = form.get("prepared_by")
        async with session_factory(request)() as session, session.begin():
            saved = await save_details(
                session,
                client_id,
                plan_text=plan if isinstance(plan, str) else "",
                owners=owners,
                asked=asked,
                prepared_by=preparer if isinstance(preparer, str) else "",
                user_id=user.id,
                now=clock_of(request)(),
            )
        if not is_htmx(request):
            return redirect(f"/clients/{client_id}/reports")
        stamp = saved.astimezone(UTC).strftime("%H:%M:%S")
        return HTMLResponse(
            f'<span role="status">Saved at {stamp} UTC.</span>',
            headers={"Cache-Control": "no-store"},
        )

    return await guarded(request, handle)


@router.post("/clients/{client_id}/reports/snapshot")
async def make_snapshot(
    request: Request,
    client_id: RowId,
    period_start: Annotated[str, Form()] = "",
    period_end: Annotated[str, Form()] = "",
) -> Response:
    """Store the state of the client today as the snapshot of a report."""

    async def handle(user: AppUser) -> Response:
        now = clock_of(request)()
        start, end = read_period(period_start.strip(), period_end.strip(), now.date())
        async with session_factory(request)() as session, session.begin():
            await lock_client(session, client_id)
            live = await load_live(session, library_of(request), client_id, now)
            snapshot_id = await store_snapshot(
                session, client_id, live.snapshot, start, end
            )
            add_audit_event(
                session,
                "snapshot.created",
                actor_user_id=user.id,
                target_type="snapshot",
                target_id=snapshot_id,
                detail={"client_id": client_id},
            )
        return redirect(f"/clients/{client_id}/reports/{snapshot_id}")

    return await guarded(request, handle)


@router.get("/clients/{client_id}/reports/{snapshot_id}")
async def report_page(
    request: Request, client_id: RowId, snapshot_id: RowId
) -> Response:
    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session:
            view = await build_report_view(
                request, session, user, client_id, snapshot_id
            )
        context: dict[str, Any] = {
            "title": f"Report - {view.context.client_name}",
            "nav": "clients",
            "client_id": client_id,
            "client_name": view.context.client_name,
            "section": "reports",
            "snapshot_id": snapshot_id,
            "view": view,
            "problems": completeness_problems(view),
            "kinds": KIND_LIST,
        }
        return page(request, "report.html", user, context)

    return await guarded(request, handle)


@router.get("/clients/{client_id}/reports/{snapshot_id}/preview/{kind}")
async def preview(
    request: Request, client_id: RowId, snapshot_id: RowId, kind: str
) -> Response:
    async def handle(user: AppUser) -> Response:
        check_kind(kind)
        async with session_factory(request)() as session:
            view = await build_report_view(
                request, session, user, client_id, snapshot_id
            )
        return Response(
            content=render_report(kind, view),
            media_type="text/html",
            headers={
                "Content-Security-Policy": PREVIEW_POLICY,
                "Cache-Control": "no-store",
            },
        )

    return await guarded(request, handle)


@router.post("/clients/{client_id}/reports/{snapshot_id}/export")
async def export(
    request: Request,
    client_id: RowId,
    snapshot_id: RowId,
    kind: Annotated[str, Form()] = "",
) -> Response:
    async def handle(user: AppUser) -> Response:
        if kind not in KINDS:
            raise FormError("Choose the report to export: the review or the pack.")
        async with session_factory(request)() as session, session.begin():
            # The lock comes first: a client being deleted is waited for, and the
            # export then finds it gone (404) instead of leaving a file behind.
            await lock_client(session, client_id)
            view = await build_report_view(
                request, session, user, client_id, snapshot_id
            )
            record, _ = await export_report(
                session,
                files_of(request),
                view,
                kind,
                client_id=client_id,
                snapshot_id=snapshot_id,
                user_id=user.id,
            )
        return redirect(f"/clients/{client_id}/exports?exported={record.id}")

    return await guarded(request, handle)


@router.get("/clients/{client_id}/exports")
async def history_page(
    request: Request, client_id: RowId, exported: str = ""
) -> Response:
    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session:
            client = await session.get(Client, client_id)
            if client is None:
                raise ClientNotFoundError("There is no client with this id.")
            records = await list_exports(session, client_id)
            wanted: set[int] = set()
            for item in records:
                if item.exported_by_id is not None:
                    wanted.add(item.exported_by_id)
            names: dict[int, str] = {}
            if wanted:
                found = await session.execute(
                    select(AppUser.id, AppUser.username).where(AppUser.id.in_(wanted))
                )
                for user_id, username in found.all():
                    names[user_id] = username
        rows: list[tuple[ExportRecord, str, str]] = []
        for item in records:
            who = names.get(item.exported_by_id or 0, "Unknown")
            rows.append((item, who, REPORT_NAMES[item.kind]))
        context: dict[str, Any] = {
            "title": f"Export history - {client.name}",
            "nav": "clients",
            "client_id": client_id,
            "client_name": client.name,
            "section": "exports",
            "rows": rows,
            "exported": exported if exported.isdecimal() else "",
        }
        return page(request, "exports.html", user, context)

    return await guarded(request, handle)


@router.get("/clients/{client_id}/exports/{export_id}/download")
async def download(request: Request, client_id: RowId, export_id: RowId) -> Response:
    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session:
            record, data = await read_export(
                session, files_of(request), client_id, export_id
            )
        return Response(
            content=data,
            media_type="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="{record.filename}"',
                "Cache-Control": "no-store",
            },
        )

    return await guarded(request, handle)
