"""Helpers for the page tests of phase 9: a signed-in user and seeded clients.

The fixtures that use them (`ui_settings`, `ui_ctx`, `ui_browser`) are in conftest.py.
"""

import re
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.clients import create_client
from app.evidence.assurance import Assurance
from app.evidence.service import EvidenceContext, NewEvidence
from helpers import NOW, create_admin, create_test_client, get_csrf, login, upload
from tools import make_generic_fixtures

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


async def many_clients(engine: AsyncEngine, ctx: EvidenceContext, count: int) -> None:
    """`count` clients with no evidence, made in one transaction."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        for number in range(count):
            await create_client(session, ctx.cipher, f"Bulk client {number:03d}")


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
