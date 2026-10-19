"""Settings and the glossary (phase 9)."""

from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request, Response
from sqlalchemy import select

from app.models import AppUser
from app.preferences import get_msp_name, set_msp_name
from app.reports.disclaimer import DISCLAIMER
from app.settings import Settings
from app.ui.auth import redirect
from app.ui.common import guarded, library_of, page, sentence
from app.web import clock_of, session_factory

router = APIRouter()


async def settings_response(
    request: Request,
    user: AppUser,
    errors: list[str],
    msp_name: str | None = None,
    saved: bool = False,
    status_code: int = 200,
) -> Response:
    """The settings page. Only the MSP name can be changed; the rest is shown."""
    async with session_factory(request)() as session:
        stored = await get_msp_name(session)
        found = await session.execute(select(AppUser.username).order_by(AppUser.id))
        usernames = list(found.scalars())
    settings: Settings = request.app.state.settings
    library = library_of(request)
    context: dict[str, Any] = {
        "title": "Settings",
        "nav": "settings",
        "msp_name": stored if msp_name is None else msp_name,
        "errors": errors,
        "saved": saved,
        "usernames": usernames,
        "disclaimer": DISCLAIMER,
        "domains": library.domains,
        "ruleset": f"{library.ruleset_id} {library.version}",
        "raw_retention_days": settings.raw_retention_days,
        "pack_retention_months": settings.pack_retention_months,
        "max_megabytes": f"{settings.import_max_bytes / 1_048_576:g}",
    }
    return page(request, "settings.html", user, context, status_code)


@router.get("/settings")
async def settings_page(request: Request, saved: str = "") -> Response:
    async def handle(user: AppUser) -> Response:
        return await settings_response(request, user, [], saved=saved == "1")

    return await guarded(request, handle)


@router.post("/settings")
async def settings_save(
    request: Request, msp_name: Annotated[str, Form()] = ""
) -> Response:
    async def handle(user: AppUser) -> Response:
        try:
            async with session_factory(request)() as session, session.begin():
                await set_msp_name(
                    session,
                    msp_name,
                    user_id=user.id,
                    now=clock_of(request)().astimezone(UTC),
                )
        except ValueError as error:
            errors = [sentence(str(error))]
            return await settings_response(request, user, errors, msp_name, False, 422)
        return redirect("/settings?saved=1")

    return await guarded(request, handle)


@router.get("/glossary")
async def glossary_page(request: Request) -> Response:
    async def handle(user: AppUser) -> Response:
        context: dict[str, Any] = {"title": "Glossary", "nav": "glossary"}
        return page(request, "glossary.html", user, context)

    return await guarded(request, handle)
