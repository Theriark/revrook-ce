"""FastAPI application: health endpoints, sign-in pages and the token API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import __version__, api
from app.clock import Clock, utcnow
from app.crypto import FieldCipher
from app.db import check_database, make_engine
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
    # Added first, so the security headers (added next) wrap its refusals too.
    app.add_middleware(
        UploadSizeLimitMiddleware, max_file_bytes=resolved.import_max_bytes
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=resolved.base_url.startswith("https://"),
    )

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
