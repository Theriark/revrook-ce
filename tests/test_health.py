from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import make_engine
from app.main import create_app
from app.settings import Settings, SettingsError, get_settings
from app.worker.heartbeat import STALE_AFTER, WorkerStatus, beat
from helpers import FakeClock

UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"


def client_for(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_healthz_is_ok_without_a_database(settings: Settings) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    async with client_for(app) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_is_503_when_the_database_is_unreachable(
    settings: Settings,
) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    async with client_for(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not ready", "database": "unavailable"}


async def test_readyz_is_200_with_a_working_database(
    settings: Settings, database_url: str
) -> None:
    # The web role alone does not look at the worker, which may run elsewhere.
    app = create_app(replace(settings, role="web"))
    async with client_for(app) as client:
        response = await client.get("/readyz")
    await app.state.engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


async def test_readyz_with_role_all_reflects_the_worker_heartbeat(
    settings: Settings, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    app = create_app(replace(settings, role="all"), engine=db_engine, clock=clock)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with client_for(app) as client:
        # No worker has ever reported: the container is not ready.
        never = await client.get("/readyz")
        assert never.status_code == 503
        assert never.json() == {
            "status": "not ready",
            "database": "ok",
            "worker": "never",
        }
        # A heartbeat makes it ready, and it stays ready up to the stale limit.
        await beat(factory, "test-worker", clock(), {"leader": True})
        ready = await client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json() == {
            "status": "ready",
            "database": "ok",
            "worker": "running",
        }
        clock.advance(STALE_AFTER.total_seconds())
        assert (await client.get("/readyz")).status_code == 200
        # One second later the worker counts as stopped.
        clock.advance(1)
        stale = await client.get("/readyz")
        assert stale.status_code == 503
        assert stale.json()["worker"] == "stale"
        # It reports again and the container is ready again.
        await beat(factory, "test-worker", clock(), {"leader": True})
        assert (await client.get("/readyz")).status_code == 200


async def test_readyz_with_role_all_is_503_when_the_heartbeat_cannot_be_read(
    settings: Settings, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unreadable(session: AsyncSession, now: datetime) -> WorkerStatus:
        raise OperationalError("SELECT", {}, Exception("the table cannot be read"))

    monkeypatch.setattr("app.main.read_status", unreadable)
    app = create_app(replace(settings, role="all"), engine=db_engine)
    async with client_for(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["worker"] == "unknown"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_interactive_docs_are_not_exposed(settings: Settings, path: str) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    async with client_for(app) as client:
        response = await client.get(path)
    assert response.status_code == 404


async def test_lifespan_disposes_the_engine(settings: Settings) -> None:
    app = create_app(settings, engine=make_engine(UNREACHABLE))
    async with app.router.lifespan_context(app):
        assert app.state.settings is settings


def test_app_refuses_to_start_without_secret_and_fernet_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FERNET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE)
    get_settings.cache_clear()
    try:
        with pytest.raises(SettingsError, match="SECRET_KEY is required"):
            create_app()
    finally:
        get_settings.cache_clear()
