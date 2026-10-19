"""The System page: the worker, the schedules, the data export and deleting a client.

It sits in its own module (and not in `app.ui.site`) because two of its answers are
not pages: the export is a zip and the deletion is a redirect.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request, Response

from app import __version__
from app.api_ops import export_response
from app.evidence.deletion import delete_client
from app.models import AppUser
from app.preferences import get_reminder_recipient
from app.settings import Settings
from app.system import load_overview
from app.ui.auth import redirect
from app.ui.common import RowId, guarded, page
from app.web import clock_of, files_of, session_factory
from app.worker.heartbeat import STALE_AFTER
from app.worker.mail import mail_configured

router = APIRouter()


def age_text(seconds: float | None) -> str:
    """How long ago, in words: 42 seconds, 3 minutes."""
    if seconds is None:
        return "never"
    whole = int(seconds)
    if whole < 120:
        return f"{whole} second{'s' if whole != 1 else ''}"
    minutes = whole // 60
    if minutes < 120:
        return f"{minutes} minutes"
    return f"{minutes // 60} hours"


@router.get("/system")
async def system_page(request: Request, deleted: str = "") -> Response:
    async def handle(user: AppUser) -> Response:
        async with session_factory(request)() as session:
            overview = await load_overview(session, clock_of(request)())
            recipient = await get_reminder_recipient(session)
        settings: Settings = request.app.state.settings
        context: dict[str, Any] = {
            "title": "System",
            "nav": "system",
            "errors": [],
            "deleted": deleted == "1",
            "version": __version__,
            "worker": overview.worker,
            "worker_label": overview.worker_label,
            "age": age_text(overview.worker.age_seconds),
            "stale_seconds": int(STALE_AFTER.total_seconds()),
            "schedules": overview.schedules,
            "clients": overview.clients,
            "mail_relay": mail_configured(settings),
            "reminder_set": recipient is not None,
            "heartbeat_url": settings.heartbeat_url is not None,
            "metrics": settings.metrics_token is not None,
            "role": settings.role,
        }
        return page(request, "system.html", user, context)

    return await guarded(request, handle)


@router.post("/system/export")
async def system_export(request: Request) -> Response:
    """Download everything as a zip of CSV files. The CSRF check applies."""

    async def handle(user: AppUser) -> Response:
        return await export_response(request, user.id)

    return await guarded(request, handle)


@router.post("/system/clients/{client_id}/delete")
async def system_delete_client(
    request: Request, client_id: RowId, confirm: Annotated[str, Form()] = ""
) -> Response:
    """Delete a client for good. `confirm` must be the exact name of the client."""

    async def handle(user: AppUser) -> Response:
        await delete_client(
            session_factory(request),
            files_of(request),
            client_id,
            confirm_name=confirm,
            actor_user_id=user.id,
            now=clock_of(request)(),
        )
        return redirect("/system?deleted=1")

    return await guarded(request, handle)
