import httpx
import pytest
from fastapi import FastAPI

from app.db import make_engine
from app.main import create_app
from app.settings import Settings, SettingsError, get_settings

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
    app = create_app(settings)
    async with client_for(app) as client:
        response = await client.get("/readyz")
    await app.state.engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_interactive_docs_are_not_exposed(
    settings: Settings, path: str
) -> None:
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
