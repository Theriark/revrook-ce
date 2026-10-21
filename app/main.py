"""FastAPI application: health endpoints, sign-in pages and the token API."""

import html
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__, api, api_ops, metrics
from app.checks.library import load_library
from app.clock import Clock, utcnow
from app.crypto import FieldCipher
from app.db import check_database, make_engine
from app.dns_resolver import make_resolver
from app.evidence.files import FileStore
from app.ext.registry import ExtensionRegistry, load_plugins
from app.importers.registry import build_default_registry
from app.limits import UploadSizeLimitMiddleware
from app.ratelimit import ConcurrencyGate
from app.security import SecurityHeadersMiddleware, SessionCodec
from app.settings import Settings, get_settings
from app.system import worker_banner
from app.ui import auth as ui_auth
from app.ui import clients as ui_clients
from app.ui import evidence as ui_evidence
from app.ui import home as ui_home
from app.ui import profiles as ui_profiles
from app.ui import reports as ui_reports
from app.ui import site as ui_site
from app.ui import system as ui_system
from app.ui.brand import STATIC_DIR
from app.ui.common import missing_page
from app.web import clock_of, csrf_protect, session_factory
from app.worker.heartbeat import read_status

HX_FORBIDDEN = (
    "Your session has ended or this page is out of date, so nothing was "
    "changed. Reload the page, sign in again if asked, and try again."
)
HX_NOT_FOUND = (
    "What this page refers to no longer exists, so nothing was changed. "
    "Reload the page."
)
HX_MESSAGES = {403: HX_FORBIDDEN, 404: HX_NOT_FOUND}
# The refusals a browser gets as the problem page: an address no page answers and
# a method a page does not take. Under these prefixes the answer stays JSON: the
# API, the health and metrics endpoints and the static files are not pages.
PAGE_REFUSALS = (404, 405)
NOT_PAGES = ("/api/", "/healthz", "/readyz", "/metrics", "/static/")
# The bare prefix of the API is not a page either (/api, without the slash).
NOT_PAGE_PATHS = frozenset({"/api"})
REFUSED_HTML = (
    '<div class="rv-errors" role="alert">'
    '<p class="rv-errors-title"><span class="rv-status-icon" aria-hidden="true">!'
    "</span> The request was refused</p><p>{message}</p></div>"
)
OUT_OF_RANGE = "A value in the request is outside what revrook can store."
logger = logging.getLogger("revrook.web")


def is_page_address(path: str) -> bool:
    """Whether a refusal of this address is shown as a page and not as JSON."""
    return path not in NOT_PAGE_PATHS and not path.startswith(NOT_PAGES)


# At most this many sign-ins are checked at once (each holds a database connection
# while Argon2 runs); the others are told to retry.
MAX_PARALLEL_LOGINS = 4


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    clock: Clock | None = None,
    extensions: ExtensionRegistry | None = None,
) -> FastAPI:
    """Build the application.

    Without arguments it reads the environment, so a missing SECRET_KEY or
    FERNET_KEY stops the process at startup (uvicorn --factory). The plugins of the
    entry point group are loaded as well: a plugin that cannot be loaded stops the
    start-up too, and with none installed (the Community Edition) there is nothing
    to load.
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
        # Every state-changing request needs the CSRF token (or a Bearer token). A
        # page request notes whether the worker has stopped reporting (the banner).
        dependencies=[Depends(csrf_protect), Depends(worker_banner)],
    )
    app.state.settings = resolved
    app.state.engine = db_engine
    app.state.session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    app.state.clock = clock or utcnow
    app.state.cipher = FieldCipher(resolved.fernet_key)
    app.state.session_codec = SessionCodec(resolved.secret_key)
    app.state.api_limiter = api.make_api_limiter()
    app.state.login_gate = ConcurrencyGate(MAX_PARALLEL_LOGINS)
    app.state.extensions = load_plugins() if extensions is None else extensions
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
        """A refusal of a page request is shown as a page or as a message.

        htmx swaps the body of the response into the page (see base.html), so a
        403 (an expired session or a stale form) or a 404 must carry a readable
        HTML message and not JSON. An address no page answers (404) or a method a
        page does not take (405), asked for as a page, is the problem page. Every
        other request keeps FastAPI's JSON answer.
        """
        message = HX_MESSAGES.get(error.status_code)
        if request.headers.get("hx-request") == "true" and message is not None:
            return HTMLResponse(
                REFUSED_HTML.format(message=html.escape(message)),
                status_code=error.status_code,
                headers={"Cache-Control": "no-store"},
            )
        page_wanted = is_page_address(request.url.path)
        if error.status_code in PAGE_REFUSALS and page_wanted:
            return await missing_page(request, error.status_code, error.headers)
        return await http_exception_handler(request, error)

    @app.exception_handler(DataError)
    async def out_of_range(request: Request, error: DataError) -> Response:
        """A value the database cannot hold is a 422, never a 500.

        The routes bound their ids, so this is the net under them: an id or a number
        past what a column stores reaches the database as a data error. A real schema
        bug would also show here as a 422, so the class of the error is logged; its
        text and statement are not, because they can hold the value that was sent.
        """
        logger.warning(
            "A database data error was refused with 422: %s",
            type(error.orig or error).__name__,
        )
        if request.headers.get("hx-request") == "true":
            return HTMLResponse(
                REFUSED_HTML.format(message=html.escape(OUT_OF_RANGE)),
                status_code=422,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse({"detail": OUT_OF_RANGE}, status_code=422)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process is up. It never touches the database."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request, response: Response) -> dict[str, str]:
        """Readiness: 200 when the database answers, 503 otherwise.

        With ROLE=all this container is the whole product, so it is also not ready
        while its worker has not reported a heartbeat in the last 90 seconds (I3).
        The web role alone does not look at the worker: it may run elsewhere.
        """
        if not await check_database(request.app.state.engine):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not ready", "database": "unavailable"}
        if request.app.state.settings.role != "all":
            return {"status": "ready", "database": "ok"}
        try:
            async with session_factory(request)() as session:
                worker = (await read_status(session, clock_of(request)())).state
        except (SQLAlchemyError, OSError):
            worker = "unknown"
        if worker != "running":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not ready", "database": "ok", "worker": worker}
        return {"status": "ready", "database": "ok", "worker": worker}

    app.include_router(ui_auth.router)
    app.include_router(ui_home.router)
    app.include_router(ui_clients.router)
    app.include_router(ui_evidence.router)
    app.include_router(ui_profiles.router)
    app.include_router(ui_reports.router)
    app.include_router(ui_site.router)
    app.include_router(ui_system.router)
    app.include_router(api.router)
    app.include_router(api_ops.router)
    app.include_router(metrics.router)
    # Stylesheets, vendored scripts and brand files, served from the same origin
    # (CSP default-src 'self').
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
