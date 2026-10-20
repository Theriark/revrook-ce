"""Helpers for the page tests of phase 9: a signed-in user and seeded clients.

The fixtures that use them (`ui_settings`, `ui_ctx`, `ui_browser`) are in conftest.py.
"""

import base64
import re
from collections.abc import Mapping
from datetime import timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.routing import Match
from starlette.types import Scope

from app.clients import create_client
from app.db import make_engine
from app.evidence.assurance import Assurance
from app.evidence.service import EvidenceContext, NewEvidence
from app.main import create_app
from app.settings import load_settings
from app.ui import clients as ui_clients
from app.ui import home as ui_home
from app.ui import reports as ui_reports
from app.ui import site as ui_site
from app.ui import system as ui_system
from helpers import NOW, create_admin, create_test_client, get_csrf, login, upload
from tools import make_generic_fixtures

UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"
# The routers of the pages of phases 9 and 10 and of the Home dashboard; each route is
# checked against the app.
PAGE_ROUTERS = (
    ui_home.router,
    ui_clients.router,
    ui_reports.router,
    ui_site.router,
    ui_system.router,
)
SAMPLE_VALUES = {
    "client_id": "1",
    "snapshot_id": "1",
    "export_id": "1",
    "exception_id": "1",
    "control_id": "PC-ACC-01",
    "kind": "qbr",
}
PARAMETER = re.compile(r"\{([a-z_]+)\}")
NAME = "Synthetic Client Ltd"
QUARTER = ("2026-07-01", "2026-09-30")
TITLE = re.compile(r"<title>(.*?)</title>")
ROW = re.compile(
    r'<tr data-control="([^"]+)" data-changed="(true|false)" '
    r'data-flagged="(true|false)">'
)
STATUS = re.compile(
    r'<span class="rv-status-([a-z-]+)">'
    r'<span class="rv-status-icon" aria-hidden="true">([^<]*)</span> ([^<]+)</span>'
)
STATUS_SPAN = re.compile(r'<span class="rv-status-(?!icon)[a-z-]+"')
EXPORTED = re.compile(r"exported=(\d+)")


async def sign_in(browser: httpx.AsyncClient, engine: AsyncEngine) -> str:
    """Create the administrator, sign in and return the CSRF token of the session."""
    await create_admin(engine)
    assert (await login(browser)).status_code == 303
    return await get_csrf(browser, "/clients")


async def seed_client(
    engine: AsyncEngine, ctx: EvidenceContext, name: str = NAME
) -> int:
    """A client with the six generic fixtures; the backup export is 100 days old."""
    client_id = await create_test_client(engine, ctx, name)
    for fixture in make_generic_fixtures.generic_fixtures():
        days = 100 if fixture.source_code == "backup-export" else 2
        evidence = NewEvidence(
            source_code=fixture.source_code,
            assurance=Assurance.AUTOMATIC_EXPORT,
            captured_at=NOW - timedelta(days=days),
            data=fixture.data,
        )
        await upload(engine, ctx, client_id, evidence, NOW)
    return client_id


async def many_clients(
    engine: AsyncEngine, ctx: EvidenceContext, count: int, evidence: bool = False
) -> None:
    """`count` clients made in one transaction.

    With `evidence`, each gets one generic fixture as evidence, the six sources taken
    in turn, so the client list and the overview read evidence rows for every client.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    made: list[int] = []
    async with factory() as session, session.begin():
        for number in range(count):
            name = f"Bulk client {number:03d}"
            made.append((await create_client(session, ctx.cipher, name)).id)
    if not evidence:
        return
    fixtures = make_generic_fixtures.generic_fixtures()
    for number, client_id in enumerate(made):
        fixture = fixtures[number % len(fixtures)]
        item = NewEvidence(
            source_code=fixture.source_code,
            assurance=Assurance.AUTOMATIC_EXPORT,
            captured_at=NOW - timedelta(days=2 + number % 60),
            data=fixture.data,
        )
        await upload(engine, ctx, client_id, item, NOW)


def route_app() -> FastAPI:
    """The application with a database it never reaches, to read its routes."""
    settings = load_settings(
        {
            "DATABASE_URL": UNREACHABLE,
            "SECRET_KEY": "test-only-secret-key-0123456789",
            "FERNET_KEY": base64.urlsafe_b64encode(bytes(32)).decode(),
        }
    )
    return create_app(settings, engine=make_engine(UNREACHABLE))


def app_answers(app: FastAPI, path: str, method: str) -> bool:
    """Whether a route of the application fully matches `method` on `path`.

    Starlette's own matching is used, so the answer does not depend on how the
    application stores an included router in `app.routes`.
    """
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    return any(route.matches(scope)[0] is Match.FULL for route in app.routes)


def page_routes(method: str) -> tuple[str, ...]:
    """The paths of the phase 9 pages that answer `method`, as the app routes them.

    Every route of the page modules is kept only when the application answers it,
    so a route that is declared but not included fails the length checks.
    """
    app = route_app()
    found: set[str] = set()
    for router in PAGE_ROUTERS:
        for route in router.routes:
            path: str = getattr(route, "path", "")
            methods = getattr(route, "methods", None) or ()
            if method in methods and app_answers(app, sample_path(path), method):
                found.add(path)
    return tuple(sorted(found))


def sample_path(template: str, values: Mapping[str, str] = SAMPLE_VALUES) -> str:
    """A route path with a value for each of its parameters.

    A parameter without a value is an error, so a new route with a new parameter
    has to be given one here before the tests run.
    """

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"no sample value for {{{name}}} in {template}")
        return values[name]

    return PARAMETER.sub(fill, template)


async def make_report(
    browser: httpx.AsyncClient, csrf: str, client_id: int, msp: bool = True
) -> str:
    """Set the MSP name, make a report for the last quarter and return its address."""
    if msp:
        saved = await browser.post(
            "/settings", data={"csrf_token": csrf, "msp_name": "Synthetic MSP Ltd"}
        )
        assert saved.status_code == 303
    made = await browser.post(
        f"/clients/{client_id}/reports/snapshot",
        data={
            "csrf_token": csrf,
            "period_start": QUARTER[0],
            "period_end": QUARTER[1],
        },
    )
    assert made.status_code == 303, made.text
    return made.headers["location"]


async def post_export(
    browser: httpx.AsyncClient, csrf: str, report: str, kind: str
) -> httpx.Response:
    """Post the export form of a report page."""
    return await browser.post(
        f"{report}/export", data={"csrf_token": csrf, "kind": kind}
    )


def title_of(html: str) -> str:
    match = TITLE.search(html)
    assert match is not None, "the page has no title"
    return match.group(1)


def rows_of(html: str) -> dict[str, tuple[bool, bool]]:
    """Control id to (changed, flagged) for every row of a checklist page."""
    return {
        control: (changed == "true", flagged == "true")
        for control, changed, flagged in ROW.findall(html)
    }


def exported_id(response: httpx.Response) -> int:
    """The id of the export a redirect after an export points to."""
    match = EXPORTED.search(response.headers["location"])
    assert match is not None, response.headers["location"]
    return int(match.group(1))
