"""First-run, sign-in, sign-out and the placeholder home page."""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.audit import add_audit_event
from app.auth import (
    SetupClosedError,
    authenticate,
    count_users,
    create_first_admin,
    get_user,
    validate_new_credentials,
)
from app.models import AppUser
from app.ratelimit import ConcurrencyGate
from app.security import SessionData, new_csrf_token
from app.ui.brand import asset_version, available_brand_files
from app.web import clock_of, current_session, session_factory, set_session_cookie

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["brand_files"] = available_brand_files()
# Read once at start-up: the files of the image do not change while it runs.
templates.env.globals["asset_version"] = asset_version()
router = APIRouter()

SETUP_TITLE = "Create the administrator"
INVALID_LOGIN = "The username or password is not correct."
SETUP_CLOSED = "Setup is closed: an administrator already exists. Sign in instead."
LOGIN_BUSY = "Many sign-ins are being checked. Wait a few seconds, then retry."
LOGIN_BUSY_RETRY_SECONDS = 5


def redirect(url: str) -> RedirectResponse:
    """A 303 so the browser follows a POST with a GET."""
    return RedirectResponse(url, status_code=303)


def render(
    request: Request,
    name: str,
    context: dict[str, Any],
    session: SessionData,
    status_code: int = 200,
) -> Response:
    response = templates.TemplateResponse(
        request,
        name,
        {**context, "csrf_token": session.csrf},
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    set_session_cookie(response, request, session)
    return response


@router.get("/")
async def home(request: Request) -> Response:
    session = current_session(request)
    async with session_factory(request)() as db:
        if await count_users(db) == 0:
            return redirect("/setup")
        user: AppUser | None = None
        if session.user_id is not None:
            user = await get_user(db, session.user_id)
    if user is None:
        return redirect("/login")
    context: dict[str, Any] = {"title": "Home", "nav": "home", "user": user}
    return render(request, "home.html", context, session)


@router.get("/setup")
async def setup_form(request: Request) -> Response:
    async with session_factory(request)() as db:
        if await count_users(db) > 0:
            return redirect("/login")
    context: dict[str, Any] = {"title": SETUP_TITLE, "errors": [], "username": ""}
    return render(request, "setup.html", context, current_session(request))


@router.post("/setup")
async def setup_submit(
    request: Request,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    confirm_password: Annotated[str, Form()] = "",
) -> Response:
    session = current_session(request)
    async with session_factory(request)() as db:
        if await count_users(db) > 0:
            raise HTTPException(status_code=403, detail=SETUP_CLOSED)
    errors = validate_new_credentials(username, password, confirm_password)
    if errors:
        context: dict[str, Any] = {
            "title": SETUP_TITLE,
            "errors": errors,
            "username": username,
        }
        return render(request, "setup.html", context, session, status_code=422)
    try:
        async with session_factory(request)() as db, db.begin():
            user = await create_first_admin(db, username, password)
    except SetupClosedError:
        raise HTTPException(status_code=403, detail=SETUP_CLOSED) from None
    response = redirect("/")
    # A new CSRF token on every change of identity (session fixation).
    set_session_cookie(
        response, request, SessionData(csrf=new_csrf_token(), user_id=user.id)
    )
    return response


@router.get("/login")
async def login_form(request: Request) -> Response:
    async with session_factory(request)() as db:
        if await count_users(db) == 0:
            return redirect("/setup")
    return render(
        request,
        "login.html",
        {"title": "Sign in", "errors": [], "username": ""},
        current_session(request),
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    session = current_session(request)
    # A sign-in holds a database connection while Argon2 checks the password, so a
    # burst of parallel sign-ins could use up the pool. Only a few run at once; the
    # others are told to wait, and nothing about them is checked or written.
    gate: ConcurrencyGate = request.app.state.login_gate
    if not gate.try_enter():
        busy = render(
            request,
            "login.html",
            {"title": "Sign in", "errors": [LOGIN_BUSY], "username": username},
            session,
            status_code=429,
        )
        busy.headers["Retry-After"] = str(LOGIN_BUSY_RETRY_SECONDS)
        return busy
    try:
        async with session_factory(request)() as db, db.begin():
            result = await authenticate(db, username, password, clock_of(request)())
    finally:
        gate.leave()
    if result.outcome == "ok" and result.user is not None:
        signed_in = redirect("/")
        set_session_cookie(
            signed_in,
            request,
            SessionData(csrf=new_csrf_token(), user_id=result.user.id),
        )
        return signed_in
    if result.outcome == "locked":
        minutes = max((result.retry_after + 59) // 60, 1)
        message = (
            "Too many failed attempts. This account is locked; "
            f"try again in {minutes} minute{'s' if minutes != 1 else ''}."
        )
        response = render(
            request,
            "login.html",
            {"title": "Sign in", "errors": [message], "username": username},
            session,
            status_code=429,
        )
        response.headers["Retry-After"] = str(result.retry_after)
        return response
    return render(
        request,
        "login.html",
        {"title": "Sign in", "errors": [INVALID_LOGIN], "username": username},
        session,
        status_code=401,
    )


@router.post("/logout")
async def logout(request: Request) -> Response:
    session = current_session(request)
    if session.user_id is not None:
        async with session_factory(request)() as db, db.begin():
            add_audit_event(db, "logout", actor_user_id=session.user_id)
    response = redirect("/login")
    set_session_cookie(response, request, SessionData(csrf=new_csrf_token()))
    return response
