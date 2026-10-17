"""Security headers and CSRF enforcement. None of these needs a database."""

import httpx
import pytest
from fastapi import FastAPI

from app.db import make_engine
from app.main import create_app
from app.security import SESSION_COOKIE, SessionCodec, SessionData
from app.settings import Settings, load_settings

UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"


def make_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def offline_app(settings: Settings) -> FastAPI:
    return create_app(settings, engine=make_engine(UNREACHABLE))


def signed_cookie(settings: Settings, csrf: str = "known-token") -> str:
    return SessionCodec(settings.secret_key).encode(SessionData(csrf=csrf))


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/missing"])
async def test_every_response_carries_the_security_headers(
    settings: Settings, path: str
) -> None:
    async with make_client(offline_app(settings)) as client:
        response = await client.get(path)
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in response.headers


async def test_an_error_response_carries_the_headers_too(settings: Settings) -> None:
    async with make_client(offline_app(settings)) as client:
        response = await client.post("/login", data={"username": "a"})
    assert response.status_code == 403
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_hsts_is_sent_only_when_base_url_is_https(env: dict[str, str]) -> None:
    secure = load_settings({**env, "BASE_URL": "https://revrook.example.test"})
    async with make_client(offline_app(secure)) as client:
        response = await client.get("/healthz")
    assert "max-age=" in response.headers["strict-transport-security"]


@pytest.mark.parametrize("path", ["/login", "/setup", "/logout"])
async def test_a_post_without_a_csrf_token_returns_403(
    settings: Settings, path: str
) -> None:
    async with make_client(offline_app(settings)) as client:
        response = await client.post(path, data={"username": "a", "password": "b"})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


async def test_a_post_with_a_session_but_no_token_returns_403(
    settings: Settings,
) -> None:
    headers = {"Cookie": f"{SESSION_COOKIE}={signed_cookie(settings)}"}
    async with make_client(offline_app(settings)) as client:
        response = await client.post("/login", data={"username": "a"}, headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize("supplied", ["wrong-token", ""])
async def test_a_post_with_the_wrong_token_returns_403(
    settings: Settings, supplied: str
) -> None:
    headers = {"Cookie": f"{SESSION_COOKIE}={signed_cookie(settings)}"}
    async with make_client(offline_app(settings)) as client:
        by_form = await client.post(
            "/login", data={"csrf_token": supplied}, headers=headers
        )
        by_header = await client.post(
            "/login", data={}, headers={**headers, "X-CSRF-Token": supplied}
        )
    assert by_form.status_code == 403
    assert by_header.status_code == 403


async def test_a_token_from_a_forged_session_is_not_accepted(
    settings: Settings,
) -> None:
    forged = SessionCodec("attacker-chosen-secret-key-01234").encode(
        SessionData(csrf="known-token")
    )
    headers = {"Cookie": f"{SESSION_COOKIE}={forged}"}
    async with make_client(offline_app(settings)) as client:
        response = await client.post(
            "/login", data={"csrf_token": "known-token"}, headers=headers
        )
    assert response.status_code == 403


async def test_get_requests_need_no_csrf_token(settings: Settings) -> None:
    async with make_client(offline_app(settings)) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200


async def test_a_bearer_request_skips_the_csrf_check(settings: Settings) -> None:
    # POST /logout without a session only redirects, so it needs no database:
    # 303 shows the CSRF check was passed over, 403 that it was applied.
    async with make_client(offline_app(settings)) as client:
        bearer = await client.post(
            "/logout", headers={"Authorization": "Bearer rvk_synthetic"}
        )
        cookie_only = await client.post("/logout")
    assert bearer.status_code == 303
    assert cookie_only.status_code == 403
