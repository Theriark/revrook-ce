"""The state of the installation: the worker, its schedules and the stale banner.

`worker_banner` is a dependency of every page request: when no worker has reported
for longer than `STALE_AFTER` (90 seconds), the pages show a banner. It reads one
row and never stops a page: a database that cannot be read just means no banner.
`load_overview` is what the System page and `GET /api/v1/system` show.
"""

from dataclasses import dataclass
from datetime import datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client, Schedule
from app.reports.status import StatusLabel
from app.web import clock_of, session_factory
from app.worker.heartbeat import RUNNING, STALE, WorkerStatus, read_status

SKIP_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})
SKIP_PREFIXES = ("/api/", "/static/")
MAX_SCHEDULES = 200
# What the System page says about the worker, always with an icon and words.
WORKER_LABELS = {
    RUNNING: StatusLabel("protected", "Worker running", "check"),
    STALE: StatusLabel("not-protected", "Worker not reporting", "cross"),
}
NEVER_LABEL = StatusLabel("not-checked", "No worker has reported yet", "question")


@dataclass(frozen=True)
class ScheduleLine:
    """One schedule row for a list."""

    id: int
    name: str
    kind: str
    cron: str
    enabled: bool
    client_name: str | None
    last_run_at: datetime | None
    next_run_at: datetime | None


@dataclass(frozen=True)
class ClientLine:
    id: int
    name: str


@dataclass(frozen=True)
class Overview:
    """What the System page shows."""

    worker: WorkerStatus
    worker_label: StatusLabel
    schedules: list[ScheduleLine]
    clients: list[ClientLine]


def worker_label(status: WorkerStatus) -> StatusLabel:
    """The words and icon for the state of the worker."""
    return WORKER_LABELS.get(status.state, NEVER_LABEL)


async def worker_banner(request: Request) -> None:
    """Mark the request when the worker is not reporting, for the page template."""
    if request.method != "GET":
        return
    path = request.url.path
    if path in SKIP_PATHS or path.startswith(SKIP_PREFIXES):
        return
    try:
        async with session_factory(request)() as session:
            status = await read_status(session, clock_of(request)())
    except (SQLAlchemyError, OSError):
        return
    if status.stale:
        request.state.worker_stale = True
        request.state.worker_minutes = max(int((status.age_seconds or 0) // 60), 1)


async def load_schedules(session: AsyncSession) -> list[ScheduleLine]:
    """The schedule rows, with the name of the client each one belongs to."""
    found = await session.execute(
        select(Schedule, Client.name)
        .outerjoin(Client, Client.id == Schedule.client_id)
        .order_by(Schedule.name)
        .limit(MAX_SCHEDULES)
    )
    return [
        ScheduleLine(
            id=row.id,
            name=row.name,
            kind=row.kind,
            cron=row.cron,
            enabled=row.enabled,
            client_name=client_name,
            last_run_at=row.last_run_at,
            next_run_at=row.next_run_at,
        )
        for row, client_name in found.all()
    ]


async def load_overview(session: AsyncSession, now: datetime) -> Overview:
    """The worker status, the schedules and the clients, as of `now`."""
    status = await read_status(session, now)
    query = select(Client.id, Client.name).order_by(Client.name)
    clients = await session.execute(query)
    return Overview(
        worker=status,
        worker_label=worker_label(status),
        schedules=await load_schedules(session),
        clients=[ClientLine(client_id, name) for client_id, name in clients.all()],
    )
