"""Helpers shared by the client pages: the signed-in user, pages and refusals.

Every page asks `guarded` for the user. Someone who is not signed in is sent to the
sign-in page (htmx is told to go there), and an error of the work itself becomes a
readable page with a 4xx status: a missing client is 404, a stale or damaged copy
409, a report that claims too much 422. A bug is still a 500, but nothing a person
can type or click gives one.
"""

import html
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import Path, Request, Response
from fastapi.responses import HTMLResponse

from app.auth import get_user
from app.checks.library import Library
from app.drafts import DraftError
from app.evidence.errors import (
    ClientNotFoundError,
    DuplicateEvidenceError,
    EvidenceError,
    EvidenceStorageError,
    EvidenceTooLargeError,
    ItemNotFoundError,
)
from app.models import AppUser
from app.reports.completeness import ExportBlockedError
from app.reports.export import ExportIntegrityError, ExportNotFoundError
from app.reports.view import ReportError
from app.snapshots import SnapshotNotFoundError
from app.ui.auth import redirect, render
from app.web import current_session, session_factory

MAX_ID = 9_223_372_036_854_775_807
MAX_PERIOD_DAYS = 400
RowId = Annotated[int, Path(ge=1, le=MAX_ID)]
ControlIdPath = Annotated[str, Path(pattern=r"^PC-[A-Z]{3}-[0-9]{2}$")]
STORE_FAILED = "The evidence store failed. Nothing was changed."
FRAGMENT = (
    '<div class="rv-errors" role="alert">'
    '<p class="rv-errors-title"><span class="rv-status-icon" aria-hidden="true">!'
    "</span> Nothing was saved</p><p>{message}</p></div>"
)
TITLES = {404: "Not found", 409: "The copy cannot be used"}
DEFAULT_TITLE = "The request was refused"

Handler = Callable[[AppUser], Awaitable[Response]]


class FormError(Exception):
    """A field of a form is missing or not valid; the message is shown to the user."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def library_of(request: Request) -> Library:
    library: Library = request.app.state.library
    return library


async def signed_in_user(request: Request) -> AppUser | None:
    """The user of the session cookie, or None (no session, or the user is gone)."""
    session = current_session(request)
    if session.user_id is None:
        return None
    async with session_factory(request)() as db:
        return await get_user(db, session.user_id)


def to_login(request: Request) -> Response:
    """The answer to a request without a user: the sign-in page."""
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": "/login"})
    return redirect("/login")


def page(
    request: Request,
    name: str,
    user: AppUser,
    context: dict[str, Any],
    status_code: int = 200,
) -> Response:
    """A page of the application with the user and the CSRF token in its context."""
    return render(
        request,
        name,
        {**context, "user": user},
        current_session(request),
        status_code,
    )


def problem(
    request: Request,
    user: AppUser,
    status_code: int,
    message: str,
    details: Sequence[str] = (),
) -> Response:
    """A refusal the user can read: a page, or a short message for htmx."""
    if is_htmx(request):
        return HTMLResponse(
            FRAGMENT.format(message=html.escape(message)),
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )
    context = {
        "title": TITLES.get(status_code, DEFAULT_TITLE),
        "nav": "",
        "message": message,
        "details": list(details),
    }
    return page(request, "problem.html", user, context, status_code)


def status_of(error: EvidenceError) -> int:
    """The HTTP status of an error of the evidence store or the reports."""
    missing = (
        ClientNotFoundError,
        ItemNotFoundError,
        ExportNotFoundError,
        SnapshotNotFoundError,
    )
    if isinstance(error, missing):
        return 404
    if isinstance(error, ExportIntegrityError | DuplicateEvidenceError):
        return 409
    if isinstance(error, EvidenceTooLargeError):
        return 413
    if isinstance(error, EvidenceStorageError):
        return 500
    return 422


def message_of(error: EvidenceError) -> str:
    if isinstance(error, EvidenceStorageError):
        return STORE_FAILED
    return str(error)


async def guarded(request: Request, handler: Handler) -> Response:
    """Run a page for the signed-in user and turn its refusals into 4xx answers."""
    user = await signed_in_user(request)
    if user is None:
        return to_login(request)
    try:
        return await handler(user)
    except FormError as error:
        return problem(request, user, error.status_code, str(error))
    except ExportBlockedError as error:
        message = "The report cannot be exported yet. Fix these, then export again."
        return problem(request, user, 422, message, error.problems)
    except ReportError as error:
        return problem(request, user, 422, f"The report cannot be made: {error}.")
    except DraftError as error:
        return problem(request, user, 422, str(error))
    except EvidenceError as error:
        return problem(request, user, status_of(error), message_of(error))
    except ValueError as error:
        message = f"The request could not be used: {error}"
        return problem(request, user, 422, message)


def sentence(text: str) -> str:
    """A message that starts with a capital and ends with a full stop."""
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def last_quarter(today: date) -> tuple[date, date]:
    """The first and last day of the last full calendar quarter before `today`."""
    this_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    end = this_start - timedelta(days=1)
    start = date(end.year, 3 * ((end.month - 1) // 3) + 1, 1)
    return start, end


def parse_day(text: str, label: str) -> date:
    """A date written 2026-09-30; FormError (422) when it is not one."""
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise FormError(f"{label} must be a date such as 2026-09-30.") from None


def read_period(start_text: str, end_text: str, today: date) -> tuple[date, date]:
    """The period of a report. Empty fields give the last full quarter."""
    first, last = last_quarter(today)
    start = parse_day(start_text, "The start of the period") if start_text else first
    end = parse_day(end_text, "The end of the period") if end_text else last
    if end < start:
        raise FormError("The period ends before it starts.")
    if end > today:
        raise FormError("The period cannot end in the future.")
    if (end - start).days > MAX_PERIOD_DAYS:
        raise FormError(f"The period is longer than {MAX_PERIOD_DAYS} days.")
    return start, end
