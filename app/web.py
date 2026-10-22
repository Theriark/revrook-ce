"""Request helpers: the signed session cookie, the CSRF check and shared state."""

from fastapi import HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import Clock
from app.crypto import FieldCipher
from app.evidence.files import FileStore
from app.evidence.service import EvidenceContext
from app.security import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    SessionCodec,
    SessionData,
    csrf_matches,
    new_csrf_token,
)
from app.theme import THEME_COOKIE, THEME_COOKIE_MAX_AGE

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_HEADER = "x-csrf-token"
CSRF_FIELD = "csrf_token"
API_PREFIX = "/api/"


def session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


def clock_of(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def cipher_of(request: Request) -> FieldCipher:
    cipher: FieldCipher = request.app.state.cipher
    return cipher


def files_of(request: Request) -> FileStore:
    files: FileStore = request.app.state.files
    return files


def evidence_context(request: Request) -> EvidenceContext:
    """The files, cipher, importers and settings the evidence functions need."""
    return EvidenceContext(
        files=files_of(request),
        cipher=cipher_of(request),
        importers=request.app.state.importers,
        settings=request.app.state.settings,
    )


def _codec(request: Request) -> SessionCodec:
    codec: SessionCodec = request.app.state.session_codec
    return codec


def _secure_cookies(request: Request) -> bool:
    base_url: str = request.app.state.settings.base_url
    return base_url.startswith("https://")


def load_session(request: Request) -> SessionData | None:
    """The session in the request cookie, or None if absent, forged or expired."""
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return _codec(request).decode(raw)


def current_session(request: Request) -> SessionData:
    """The request's session, or a fresh anonymous one (not yet sent to the browser)."""
    return load_session(request) or SessionData(csrf=new_csrf_token())


def set_session_cookie(
    response: Response, request: Request, session: SessionData
) -> None:
    """Send the session. HttpOnly and SameSite=Lax; Secure when BASE_URL is https."""
    response.set_cookie(
        SESSION_COOKIE,
        _codec(request).encode(session),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_secure_cookies(request),
        samesite="lax",
        path="/",
    )


async def csrf_protect(request: Request) -> None:
    """Reject a state-changing request that lacks the session's CSRF token.

    The token comes from the X-CSRF-Token header (htmx, API clients) or the
    csrf_token form field. A request to the API that authenticates with a Bearer
    token has no ambient credential for a third-party page to abuse, so it is
    exempt. A Bearer header on any other path (a page that uses the cookie) is not.
    """
    if request.method in SAFE_METHODS:
        return
    bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
    if bearer and request.url.path.startswith(API_PREFIX):
        return
    session = load_session(request)
    supplied = request.headers.get(CSRF_HEADER)
    if supplied is None and session is not None:
        form = await request.form()
        value = form.get(CSRF_FIELD)
        supplied = value if isinstance(value, str) else None
    if session is None or not supplied or not csrf_matches(session.csrf, supplied):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


def set_theme_cookie(response: Response, request: Request, theme: str) -> None:
    """Remember the theme for the pages drawn before anyone is signed in.

    The same flags as the session cookie; the value is one of the three words of
    app/theme.py and nothing a page would act on without checking it again.
    """
    response.set_cookie(
        THEME_COOKIE,
        theme,
        max_age=THEME_COOKIE_MAX_AGE,
        httponly=True,
        secure=_secure_cookies(request),
        samesite="lax",
        path="/",
    )
