"""FastAPI application: health endpoints, sign-in pages and the token API."""

import html
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__, api
from app.checks.library import load_library
from app.clock import Clock, utcnow
from app.crypto import FieldCipher
from app.db import check_database, make_engine
from app.dns_resolver import make_resolver
from app.evidence.files import FileStore
from app.importers.registry import build_default_registry
from app.limits import UploadSizeLimitMiddleware
from app.security import SecurityHeadersMiddleware, SessionCodec
from app.settings import Settings, get_settings
from app.ui import auth as ui_auth
from app.ui import evidence as ui_evidence
from app.ui import profiles as ui_profiles
from app.ui.brand import STATIC_DIR
from app.web import csrf_protect

HX_FORBIDDEN = (
    "Your session has ended or this page is out of date, so nothing was "
    "changed. Reload the page, sign in again if asked, and try again."
)
REFUSED_HTML = (
    '<div class="rv-errors" role="alert">'
    '<p class="rv-errors-title"><span class="rv-status-icon" aria-hidden="true">!'
    "</span> The request was refused</p><p>{message}</p></div>"
)


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    """Build the application.

    Without arguments it reads the environment, so a missing SECRET_KEY or
    FERNET_KEY stops the process at startup (uvicorn --factory).
    """
    resolved = settings or get_settings()
    db_engine = engine or make_engine(resolved.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await db_engine.dispose()

    app = FastAPI(
        title="revrook",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        # Every state-changing request needs the CSRF token (or a Bearer token).
        dependencies=[Depends(csrf_protect)],
    )
    app.state.settings = resolved
    app.state.engine = db_engine
    app.state.session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    app.state.clock = clock or utcnow
    app.state.cipher = FieldCipher(resolved.fernet_key)
    app.state.session_codec = SessionCodec(resolved.secret_key)
    app.state.api_limiter = api.make_api_limiter()
    app.state.files = FileStore(resolved.evidence_dir)
    app.state.importers = build_default_registry()
    app.state.library = load_library()
    app.state.dns_resolver = make_resolver(resolved.dns_resolver)
    # Added first, so the security headers (added next) wrap its refusals too.
    app.add_middleware(
        UploadSizeLimitMiddleware, max_file_bytes=resolved.import_max_bytes
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=resolved.base_url.startswith("https://"),
    )

    @app.exception_handler(StarletteHTTPException)
    async def refusal(request: Request, error: StarletteHTTPException) -> Response:
        """A refusal of a page request made by htmx is shown as a message.

        htmx swaps the body of the response into the page (see base.html), so a
        403 (an expired session or a stale form) must carry a readable HTML
        message and not JSON. Every other request keeps FastAPI's JSON answer.
        """
        if request.headers.get("hx-request") == "true" and error.status_code == 403:
            return HTMLResponse(
                REFUSED_HTML.format(message=html.escape(HX_FORBIDDEN)),
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        return await http_exception_handler(request, error)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process is up. It never touches the database."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request, response: Response) -> dict[str, str]:
        """Readiness: 200 when the database answers, 503 otherwise."""
        if await check_database(request.app.state.engine):
            return {"status": "ready", "database": "ok"}
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not ready", "database": "unavailable"}

    app.include_router(ui_auth.router)
    app.include_router(ui_evidence.router)
    app.include_router(ui_profiles.router)
    app.include_router(api.router)
    # Stylesheets, vendored scripts and brand files, served from the same origin
    # (CSP default-src 'self').
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
