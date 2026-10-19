"""The operations part of the JSON API: schedules, snapshot requests, export, status.

Same authentication as `app.api` (a Bearer API token, rate limited per token).

* `GET/POST /schedules` and `DELETE /schedules/{id}`: the rows the worker runs.
* `POST /clients/{id}/snapshot-requests`: ask the worker to build a snapshot of a
  client for the last full quarter. It is a one-time schedule; asking twice while the
  first is waiting returns the first.
* `GET /export`: the full data export as one zip of CSV files, without personal
  identifiers (`app.dataexport`).
* `GET /system`: whether a worker is reporting.
"""

import asyncio
import secrets
from collections.abc import AsyncIterator
from datetime import datetime
from tempfile import SpooledTemporaryFile
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api import CurrentUser, http_error
from app.audit import add_audit_event
from app.checks.dnscheck import (
    MAX_DOMAINS,
    MAX_NAME_LENGTH,
    MAX_PROVIDERS,
    MAX_SELECTORS,
    clean_domains,
    clean_providers,
    clean_selectors,
)
from app.dataexport import build_export, file_size
from app.evidence.errors import ClientNotFoundError, EvidenceError
from app.evidence.locking import lock_client
from app.limits import MAX_ID, RowId
from app.models import Client, Schedule
from app.system import ScheduleLine, load_schedules
from app.textcheck import control_character
from app.web import clock_of, session_factory
from app.worker.cron import ONCE, CronError, next_run_for, validate_cron
from app.worker.heartbeat import STALE_AFTER, read_status
from app.worker.scheduler import (
    CLIENT_KINDS,
    DNS_CHECK,
    GLOBAL_KINDS,
    KINDS,
    SNAPSHOT_BUILD,
)

router = APIRouter(prefix="/api/v1")

MAX_NAME = 100
EXPORT_CHUNK_BYTES = 256 * 1024
Domain = Annotated[str, Field(max_length=MAX_NAME_LENGTH)]


class ScheduleCreate(BaseModel):
    """A new schedule. Mail domains are for a DNS check only."""

    kind: str
    cron: str
    client_id: int | None = Field(default=None, ge=1, le=MAX_ID)
    name: str | None = None
    domains: list[Domain] = Field(default_factory=list, max_length=MAX_DOMAINS)
    selectors: list[Domain] = Field(default_factory=list, max_length=MAX_SELECTORS)
    providers: list[Domain] = Field(default_factory=list, max_length=MAX_PROVIDERS)


def schedule_json(line: ScheduleLine) -> dict[str, object]:
    return {
        "id": line.id,
        "name": line.name,
        "kind": line.kind,
        "cron": line.cron,
        "enabled": line.enabled,
        "client": line.client_name,
        "last_run_at": line.last_run_at.isoformat() if line.last_run_at else None,
        "next_run_at": line.next_run_at.isoformat() if line.next_run_at else None,
    }


def _refuse(message: str, status_code: int = 422) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


def _config(body: ScheduleCreate) -> dict[str, list[str]]:
    """The config of a schedule: the checked mail domains of a DNS check."""
    if body.kind != DNS_CHECK:
        if body.domains or body.selectors or body.providers:
            raise _refuse("Mail domains are only for a dns-check schedule.")
        return {}
    try:
        return {
            "domains": list(clean_domains(body.domains)),
            "selectors": list(clean_selectors(body.selectors)),
            "providers": list(clean_providers(body.providers)),
        }
    except ValueError as error:
        raise _refuse(str(error)) from None


def _name(body: ScheduleCreate) -> str:
    chosen = (body.name or "").strip()
    if not chosen:
        suffix = f"-client-{body.client_id}" if body.client_id else ""
        chosen = f"{body.kind}{suffix}"
    if len(chosen) > MAX_NAME or control_character(chosen) is not None:
        raise _refuse(f"The name must be 1 to {MAX_NAME} characters, no controls.")
    return chosen


def _check_scope(body: ScheduleCreate) -> None:
    if body.kind not in KINDS:
        raise _refuse(f"The kind must be one of: {', '.join(KINDS)}.")
    if body.kind in CLIENT_KINDS and body.client_id is None:
        raise _refuse(f"A {body.kind} schedule needs a client_id.")
    if body.kind in GLOBAL_KINDS and body.client_id is not None:
        raise _refuse(f"A {body.kind} schedule is for the whole installation.")


async def _require_client(session: AsyncSession, client_id: int) -> None:
    if await session.get(Client, client_id) is None:
        raise http_error(ClientNotFoundError("There is no client with this id."))


async def _insert_schedule(
    session: AsyncSession,
    user_id: int,
    name: str,
    kind: str,
    cron: str,
    client_id: int | None,
    config: dict[str, list[str]],
    first: datetime | None,
) -> int:
    """Add the row and its audit event to the open transaction; returns its id."""
    row = Schedule(
        name=name,
        kind=kind,
        cron=cron,
        client_id=client_id,
        next_run_at=first,
        config=config,
    )
    session.add(row)
    await session.flush()
    add_audit_event(
        session,
        "schedule.created",
        actor_user_id=user_id,
        target_type="schedule",
        target_id=row.id,
        detail={"kind": kind, "client_id": client_id},
    )
    return row.id


async def _add_schedule(
    request: Request,
    user_id: int,
    name: str,
    kind: str,
    cron: str,
    client_id: int | None,
    config: dict[str, list[str]],
) -> tuple[int, datetime | None]:
    now = clock_of(request)()
    first = now if cron == ONCE else next_run_for(cron, now)
    try:
        async with session_factory(request)() as session, session.begin():
            if client_id is not None:
                await _require_client(session, client_id)
            schedule_id = await _insert_schedule(
                session, user_id, name, kind, cron, client_id, config, first
            )
    except IntegrityError:
        raise _refuse("A schedule with this name already exists.", 409) from None
    return schedule_id, first


@router.get("/schedules")
async def get_schedules(request: Request, user: CurrentUser) -> dict[str, object]:
    """Every schedule with its last and next run (UTC)."""
    async with session_factory(request)() as session:
        lines = await load_schedules(session)
    return {"schedules": [schedule_json(line) for line in lines]}


@router.post("/schedules", status_code=201)
async def post_schedule(
    request: Request, body: ScheduleCreate, user: CurrentUser
) -> dict[str, object]:
    """Add a schedule. `cron` is five fields in UTC, a macro, or @once."""
    _check_scope(body)
    try:
        cron = validate_cron(body.cron)
    except CronError as error:
        raise _refuse(f"The cron expression is not valid: {error}.") from None
    schedule_id, first = await _add_schedule(
        request,
        user.id,
        _name(body),
        body.kind,
        cron,
        body.client_id,
        _config(body),
    )
    return {
        "id": schedule_id,
        "next_run_at": first.isoformat() if first is not None else None,
    }


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    request: Request, schedule_id: RowId, user: CurrentUser
) -> dict[str, object]:
    async with session_factory(request)() as session, session.begin():
        row = await session.get(Schedule, schedule_id)
        if row is None:
            raise _refuse("There is no schedule with this id.", 404)
        await session.delete(row)
        add_audit_event(
            session,
            "schedule.deleted",
            actor_user_id=user.id,
            target_type="schedule",
            target_id=schedule_id,
            detail={"kind": row.kind},
        )
    return {"deleted": schedule_id}


@router.post("/clients/{client_id}/snapshot-requests", status_code=202)
async def post_snapshot_request(
    request: Request, client_id: RowId, user: CurrentUser
) -> dict[str, object]:
    """Ask the worker to build a snapshot of the client (last full quarter).

    The check for a request that is already waiting and the insert of a new one
    are one transaction under the lock of the client, so two requests at once
    queue one snapshot: the second waits for the lock, finds the first and returns it.
    """
    now = clock_of(request)()
    stamp = now.strftime("%Y%m%dT%H%M%S")
    name = f"snapshot-request-{client_id}-{stamp}-{secrets.token_hex(3)}"
    try:
        async with session_factory(request)() as session, session.begin():
            try:
                await lock_client(session, client_id)
            except ClientNotFoundError as error:
                raise http_error(error) from None
            waiting = await session.execute(
                select(Schedule.id).where(
                    Schedule.kind == SNAPSHOT_BUILD,
                    Schedule.client_id == client_id,
                    Schedule.cron == ONCE,
                    Schedule.enabled.is_(True),
                )
            )
            existing = waiting.scalars().first()
            if existing is not None:
                return {"id": existing, "queued": False}
            schedule_id = await _insert_schedule(
                session, user.id, name, SNAPSHOT_BUILD, ONCE, client_id, {}, now
            )
    except IntegrityError:
        raise _refuse("A schedule with this name already exists.", 409) from None
    return {"id": schedule_id, "queued": True}


async def _chunks(file: SpooledTemporaryFile[bytes]) -> AsyncIterator[bytes]:
    """The file in pieces, read off the event loop; closes it when done."""
    try:
        while piece := await asyncio.to_thread(file.read, EXPORT_CHUNK_BYTES):
            yield piece
    finally:
        file.close()


async def export_response(request: Request, user_id: int) -> Response:
    """The data export as a download, audited (API and System page).

    The zip is built in a temporary file (see `app.dataexport`) and sent from it in
    pieces. An export over the size cap raises ExportTooLargeError (413).
    """
    now = clock_of(request)()
    async with session_factory(request)() as session:
        spool, counts = await build_export(session, now, __version__)
        try:
            add_audit_event(
                session,
                "data.exported",
                actor_user_id=user_id,
                detail={"files": len(counts), "rows": sum(counts.values())},
            )
            await session.commit()
            size = file_size(spool)
        except BaseException:
            spool.close()
            raise
    name = f"revrook-export-{now.strftime('%Y%m%d')}.zip"
    return StreamingResponse(
        _chunks(spool),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Length": str(size),
            "Cache-Control": "no-store",
        },
    )


@router.get("/export")
async def get_export(request: Request, user: CurrentUser) -> Response:
    """Everything revrook holds as a zip of CSV files, with no personal identifiers."""
    try:
        return await export_response(request, user.id)
    except EvidenceError as error:
        raise http_error(error) from None


@router.get("/system")
async def get_system(request: Request, user: CurrentUser) -> dict[str, object]:
    """Whether a worker is reporting, from the heartbeat table."""
    async with session_factory(request)() as session:
        status = await read_status(session, clock_of(request)())
    return {
        "version": __version__,
        "worker": {
            "state": status.state,
            "last_beat": status.last_beat.isoformat() if status.last_beat else None,
            "age_seconds": status.age_seconds,
            "workers": status.workers,
        },
        "stale_after_seconds": int(STALE_AFTER.total_seconds()),
    }
