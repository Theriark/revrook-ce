"""FastAPI application: liveness and readiness endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncEngine

from app import __version__
from app.db import check_database, make_engine
from app.settings import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
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
    )
    app.state.settings = resolved
    app.state.engine = db_engine

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

    return app
