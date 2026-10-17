"""Shared helpers for the database and web tests (synthetic data only)."""

import re
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth import create_first_admin
from app.models import AuditEvent

PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "not the right password at all"
CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


class FakeClock:
    """A settable clock for lockout tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def create_admin(
    engine: AsyncEngine, username: str = "admin", password: str = PASSWORD
) -> int:
    """Create the first administrator directly and return its id."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        user = await create_first_admin(session, username, password)
    return user.id


def csrf_from(html: str) -> str:
    """The CSRF token of the first form in a page."""
    match = CSRF_FIELD.search(html)
    assert match is not None, "the page has no csrf_token field"
    return match.group(1)


async def get_csrf(client: httpx.AsyncClient, path: str) -> str:
    """Open a page and return the CSRF token of its form."""
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return csrf_from(response.text)


async def login(
    client: httpx.AsyncClient,
    password: str = PASSWORD,
    username: str = "admin",
    token: str | None = None,
) -> httpx.Response:
    """Post the sign-in form; fetches a CSRF token unless one is given."""
    csrf = token or await get_csrf(client, "/login")
    return await client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf},
    )


async def audit_baseline(engine: AsyncEngine) -> int:
    """The newest audit_event id now (the table is never emptied)."""
    factory = async_sessionmaker(engine)
    async with factory() as session:
        newest = select(func.coalesce(func.max(AuditEvent.id), 0))
        return int((await session.execute(newest)).scalar_one())


async def audit_since(engine: AsyncEngine, baseline: int) -> list[AuditEvent]:
    """Audit rows written after the baseline, oldest first."""
    factory = async_sessionmaker(engine)
    async with factory() as session:
        result = await session.execute(
            select(AuditEvent).where(AuditEvent.id > baseline).order_by(AuditEvent.id)
        )
        return list(result.scalars())
