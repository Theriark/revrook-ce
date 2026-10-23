"""A report leaves revrook as the bytes that were hashed (THE-975).

An edge that rewrites HTML (Cloudflare Email Address Obfuscation) changed the served
export of the Dev site: other size, another hash on every download, and addresses
replaced by a placeholder. These tests pin what the application can do about it: the
download is an opaque attachment, every response that is still HTML says
`no-transform`, and the bytes sent are the bytes the history records.

The tests that need PostgreSQL (DATABASE_URL) are skipped without it. The others run
anywhere.
"""

import hashlib

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.service import EvidenceContext
from app.models import ReportExport
from app.security import SecurityHeadersMiddleware, with_no_transform
from ui_helpers import make_report, post_export, seed_client, sign_in

EMAIL_PAGE = "<p>Prepared by <a href='mailto:a@example.org'>a@example.org</a></p>"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (None, "no-transform"),
        ("", "no-transform"),
        ("no-store", "no-store, no-transform"),
        ("private, max-age=0", "private, max-age=0, no-transform"),
        ("no-store, no-transform", "no-store, no-transform"),
        ("No-Transform", "No-Transform"),
    ],
)
def test_no_transform_is_added_once(given: str | None, expected: str) -> None:
    assert with_no_transform(given) == expected


def middleware_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/page")
    async def page() -> Response:
        return HTMLResponse(EMAIL_PAGE)

    @app.get("/cached")
    async def cached() -> Response:
        return HTMLResponse(EMAIL_PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/data")
    async def data() -> Response:
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    return app


async def get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=middleware_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get(path)


async def test_an_html_response_without_a_cache_policy_gets_no_transform() -> None:
    response = await get("/page")
    assert response.headers["cache-control"] == "no-transform"
    assert response.content == EMAIL_PAGE.encode()


async def test_an_html_response_keeps_its_policy_and_gains_no_transform() -> None:
    response = await get("/cached")
    assert response.headers["cache-control"] == "no-store, no-transform"


async def test_a_response_that_is_not_html_is_left_alone() -> None:
    response = await get("/data")
    assert response.headers["cache-control"] == "no-store"


async def test_the_download_is_the_recorded_file_byte_for_byte(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)
    exported = await post_export(ui_browser, csrf, report, "qbr")
    assert exported.status_code == 303
    export_id = int(exported.headers["location"].rsplit("=", 1)[1])
    async with async_sessionmaker(db_engine)() as session:
        row = await session.get(ReportExport, export_id)
    assert row is not None

    first = await ui_browser.get(f"/clients/{client_id}/exports/{export_id}/download")
    second = await ui_browser.get(f"/clients/{client_id}/exports/{export_id}/download")

    for served in (first, second):
        assert served.status_code == 200
        # Opaque, so an edge that rewrites text/html leaves it alone.
        assert served.headers["content-type"] == "application/octet-stream"
        assert served.headers["content-disposition"] == (
            f'attachment; filename="{row.filename}"'
        )
        cache = [part.strip() for part in served.headers["cache-control"].split(",")]
        assert "no-store" in cache and "no-transform" in cache
        # What was listed is what is served: size and hash.
        assert len(served.content) == row.size_bytes
        assert hashlib.sha256(served.content).hexdigest() == row.file_sha256
    assert first.content == second.content


async def test_the_preview_and_the_report_page_say_no_transform(
    ui_browser: httpx.AsyncClient, db_engine: AsyncEngine, ui_ctx: EvidenceContext
) -> None:
    csrf = await sign_in(ui_browser, db_engine)
    client_id = await seed_client(db_engine, ui_ctx)
    report = await make_report(ui_browser, csrf, client_id)
    for path in (report, f"{report}/preview/qbr"):
        served = await ui_browser.get(path)
        assert served.status_code == 200
        assert served.headers["content-type"].startswith("text/html")
        cache = [part.strip() for part in served.headers["cache-control"].split(",")]
        assert "no-store" in cache and "no-transform" in cache
