"""Prometheus metrics, off unless METRICS_TOKEN is set.

`GET /metrics` answers 404 when no token is configured, and otherwise needs
`Authorization: Bearer <METRICS_TOKEN>`. The text is the Prometheus exposition format,
written here (no client library). Only totals are exported: never a client name, an
identifier or a label that grows with the data, so a scrape reveals how big the
installation is and whether its worker is alive, and nothing about who it serves.

The names are fixed by `METRICS` and checked by a test, because a dashboard or an
alert breaks when one changes.
"""

import hmac
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.models import (
    AuditEvent,
    Client,
    EvidenceItem,
    ReportExport,
    Schedule,
    Snapshot,
)
from app.web import clock_of, session_factory
from app.worker.heartbeat import read_status

router = APIRouter()

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
# A schedule whose time passed this long ago, and was not run, is overdue.
OVERDUE_AFTER = timedelta(minutes=5)
# name, type, help
METRICS = (
    ("revrook_build_info", "gauge", "Build information; the value is always 1."),
    ("revrook_clients", "gauge", "Clients."),
    ("revrook_evidence_items", "gauge", "Evidence items."),
    ("revrook_snapshots", "gauge", "Stored snapshots."),
    ("revrook_report_exports", "gauge", "Exported reports kept."),
    ("revrook_audit_events_total", "counter", "Audit events written."),
    ("revrook_schedules_enabled", "gauge", "Enabled schedules."),
    ("revrook_schedules_overdue", "gauge", "Enabled schedules that are late."),
    ("revrook_worker_up", "gauge", "1 when a worker reported recently, else 0."),
    (
        "revrook_worker_heartbeat_age_seconds",
        "gauge",
        "Seconds since the newest worker heartbeat; NaN before the first.",
    ),
)


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _total(model: Any) -> Select[Any]:
    """A count of the rows of a table."""
    return select(func.count()).select_from(model)


async def _count(session: AsyncSession, query: Select[Any]) -> int:
    return int((await session.execute(query)).scalar_one())


async def collect(session: AsyncSession, now: datetime) -> dict[str, str]:
    """The value of every metric, as the text that follows its name."""
    status = await read_status(session, now)
    enabled = _total(Schedule).where(Schedule.enabled.is_(True))
    overdue = enabled.where(Schedule.next_run_at < now - OVERDUE_AFTER)
    age = "NaN" if status.age_seconds is None else f"{status.age_seconds:.1f}"
    return {
        "revrook_build_info": f'{{version="{_label(__version__)}"}} 1',
        "revrook_clients": str(await _count(session, _total(Client))),
        "revrook_evidence_items": str(await _count(session, _total(EvidenceItem))),
        "revrook_snapshots": str(await _count(session, _total(Snapshot))),
        "revrook_report_exports": str(await _count(session, _total(ReportExport))),
        "revrook_audit_events_total": str(await _count(session, _total(AuditEvent))),
        "revrook_schedules_enabled": str(await _count(session, enabled)),
        "revrook_schedules_overdue": str(await _count(session, overdue)),
        "revrook_worker_up": "1" if status.running else "0",
        "revrook_worker_heartbeat_age_seconds": age,
    }


def render(values: dict[str, str]) -> str:
    """The exposition text. Every metric has a HELP and a TYPE line."""
    lines: list[str] = []
    for name, kind, help_text in METRICS:
        value = values[name]
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        # A value that starts with { carries labels, so it follows the name directly.
        separator = "" if value.startswith("{") else " "
        lines.append(f"{name}{separator}{value}")
    return "\n".join(lines) + "\n"


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    token: str | None = request.app.state.settings.metrics_token
    if not token:
        raise HTTPException(status_code=404, detail="Not found")
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    given = supplied.strip().encode()
    if scheme.lower() != "bearer" or not hmac.compare_digest(given, token.encode()):
        raise HTTPException(
            status_code=401,
            detail="A valid metrics token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    async with session_factory(request)() as session:
        values = await collect(session, clock_of(request)())
    return Response(
        render(values),
        media_type=CONTENT_TYPE,
        headers={"Cache-Control": "no-store"},
    )
