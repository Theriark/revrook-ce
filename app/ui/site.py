"""Settings and the glossary (phase 9), and the reminder address (phase 10)."""

from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request, Response
from sqlalchemy import select, update

from app.models import AppUser
from app.preferences import (
    get_msp_name,
    get_reminder_recipient,
    set_msp_name,
    set_reminder_recipient,
)
from app.reports.disclaimer import DISCLAIMER
from app.settings import Settings
from app.theme import RAILS, THEMES, safe_next
from app.ui.auth import redirect
from app.ui.common import (
    guarded,
    is_htmx,
    library_of,
    page,
    sentence,
    signed_in_user,
)
from app.web import clock_of, session_factory, set_rail_cookie, set_theme_cookie
from app.worker.mail import mail_configured

router = APIRouter()


async def settings_response(
    request: Request,
    user: AppUser,
    errors: list[str],
    msp_name: str | None = None,
    saved: bool = False,
    status_code: int = 200,
    reminder_email: str | None = None,
) -> Response:
    """The settings page. The MSP name and the reminder address can be changed."""
    async with session_factory(request)() as session:
        stored = await get_msp_name(session)
        stored_reminder = await get_reminder_recipient(session)
        found = await session.execute(select(AppUser.username).order_by(AppUser.id))
        usernames = list(found.scalars())
    settings: Settings = request.app.state.settings
    library = library_of(request)
    reminder = stored_reminder or ""
    if reminder_email is not None:
        reminder = reminder_email
    context: dict[str, Any] = {
        "title": "Settings",
        "nav": "settings",
        "msp_name": stored if msp_name is None else msp_name,
        "reminder_email": reminder,
        "mail_relay": mail_configured(settings),
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
    request: Request,
    msp_name: Annotated[str, Form()] = "",
    reminder_email: Annotated[str | None, Form()] = None,
) -> Response:
    """Save the MSP name and, when the form has the field, the reminder address.

    One transaction: when either is refused nothing is changed.
    """

    async def handle(user: AppUser) -> Response:
        now = clock_of(request)().astimezone(UTC)
        try:
            async with session_factory(request)() as session, session.begin():
                await set_msp_name(session, msp_name, user_id=user.id, now=now)
                if reminder_email is not None:
                    await set_reminder_recipient(
                        session, reminder_email, user_id=user.id, now=now
                    )
        except ValueError as error:
            errors = [sentence(str(error))]
            return await settings_response(
                request, user, errors, msp_name, False, 422, reminder_email
            )
        return redirect("/settings?saved=1")

    return await guarded(request, handle)


@router.get("/glossary")
async def glossary_page(request: Request) -> Response:
    async def handle(user: AppUser) -> Response:
        context: dict[str, Any] = {"title": "Glossary", "nav": "glossary"}
        return page(request, "glossary.html", user, context)

    return await guarded(request, handle)


@router.post("/theme")
async def theme_save(
    request: Request,
    theme: Annotated[str, Form()] = "",
    next_path: Annotated[str, Form(alias="next")] = "/",
) -> Response:
    """Remember the theme chosen with the switch (_theme.html, app/theme.py).

    Signed in, it is written on the user row and the page comes back in the new
    theme; the cookie is set too, so the sign-in page follows. Signed out (the
    sign-in and first-run pages) only the cookie is set, and the way back is the
    sign-in page, as for every form posted without a user. htmx gets 204: the
    script has applied the theme already.
    """
    if theme not in THEMES:
        raise HTTPException(
            status_code=422, detail="The theme must be light, dark or system."
        )
    user = await signed_in_user(request)
    if user is not None and user.theme != theme:
        async with session_factory(request)() as session, session.begin():
            await session.execute(
                update(AppUser).where(AppUser.id == user.id).values(theme=theme)
            )
    if is_htmx(request):
        response: Response = Response(status_code=204)
    else:
        response = redirect(safe_next(next_path) if user is not None else "/login")
    set_theme_cookie(response, request, theme)
    return response


@router.post("/rail")
async def rail_save(
    request: Request,
    rail: Annotated[str, Form()] = "",
    next_path: Annotated[str, Form(alias="next")] = "/",
) -> Response:
    """Remember whether the rail is open or folded (_rail.html, app/theme.py).

    A browser preference: the cookie alone keeps it, signed in or not, since the
    rail is drawn only for a signed-in person and the choice is about this screen.
    htmx gets 204, the script has folded the rail already; without script the
    page comes back with the rail as chosen.
    """
    if rail not in RAILS:
        raise HTTPException(
            status_code=422, detail="The rail must be expanded or compact."
        )
    user = await signed_in_user(request)
    if is_htmx(request):
        response: Response = Response(status_code=204)
    else:
        response = redirect(safe_next(next_path) if user is not None else "/login")
    set_rail_cookie(response, request, rail)
    return response
