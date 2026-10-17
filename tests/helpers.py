"""Shared helpers for the database and web tests (synthetic data only)."""

import contextlib
import json
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth import create_first_admin, issue_api_token
from app.clients import create_client
from app.crypto import FieldCipher
from app.evidence.assurance import Assurance
from app.evidence.files import FileStore
from app.evidence.service import (
    EvidenceContext,
    NewEvidence,
    StoredEvidence,
    add_evidence,
)
from app.importers.registry import build_default_registry
from app.models import AppUser, AuditEvent
from app.settings import Settings

PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "not the right password at all"
CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
# Synthetic identifiers. No real person or tenant appears in any test.
SYNTHETIC_USERS = (
    ("alice.synthetic@example.test", True),
    ("bob.synthetic@example.test", False),
    ("carol.synthetic@example.test", True),
)
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
LOG_COLUMNS = (
    "id",
    "client_id",
    "evidence_item_id",
    "event_type",
    "payload",
    "previous_hash",
    "record_hash",
    "created_at",
)
DISABLE_TRIGGERS = text("ALTER TABLE evidence_log DISABLE TRIGGER USER")
ENABLE_TRIGGERS = text("ALTER TABLE evidence_log ENABLE TRIGGER USER")
COLUMNS = ", ".join(LOG_COLUMNS)
SELECT_LOG = text(
    f"SELECT {COLUMNS} FROM evidence_log WHERE client_id = :client_id ORDER BY id"
)
DELETE_LOG = text("DELETE FROM evidence_log WHERE client_id = :client_id")
INSERT_LOG = text(
    f"INSERT INTO evidence_log ({COLUMNS}) VALUES (:id, :client_id, "
    ":evidence_item_id, :event_type, CAST(:payload AS jsonb), :previous_hash, "
    ":record_hash, :created_at)"
)


class FakeClock:
    """A settable clock for lockout tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def issue_token(engine: AsyncEngine, username: str = "admin") -> str:
    """Create an administrator and return an API token for it."""
    user_id = await create_admin(engine, username)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        user = await session.get(AppUser, user_id)
        assert user is not None
        return await issue_api_token(session, user, "tests")


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


def users_csv(users: tuple[tuple[str, bool], ...] = SYNTHETIC_USERS) -> bytes:
    """A synthetic user list in the format of the reference importer."""
    lines = ["user_principal_name,mfa_registered"]
    lines += [f"{upn},{'true' if flag else 'false'}" for upn, flag in users]
    return ("\n".join(lines) + "\n").encode("utf-8")


def make_context(settings: Settings, root: Path, **changes: Any) -> EvidenceContext:
    """An evidence context on a temporary directory, with optional setting changes."""
    resolved = replace(settings, **changes)
    return EvidenceContext(
        files=FileStore(root),
        cipher=FieldCipher(resolved.fernet_key),
        importers=build_default_registry(),
        settings=resolved,
    )


async def create_test_client(
    engine: AsyncEngine, ctx: EvidenceContext, name: str = "Synthetic Client Ltd"
) -> int:
    """Create a client with its own pseudonym key and return its id."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        client = await create_client(session, ctx.cipher, name)
    return client.id


def export_evidence(
    data: bytes | None = None, captured_at: datetime | None = None
) -> NewEvidence:
    """An automatic export of the reference source, captured two days ago."""
    return NewEvidence(
        source_code="reference-csv",
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=captured_at or NOW - timedelta(days=2),
        data=users_csv() if data is None else data,
    )


async def upload(
    engine: AsyncEngine,
    ctx: EvidenceContext,
    client_id: int,
    evidence: NewEvidence,
    now: datetime | None = None,
) -> StoredEvidence:
    """Add evidence in its own transaction, as the API does."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        return await add_evidence(session, ctx, client_id, evidence, now or NOW)


async def scalar(engine: AsyncEngine, statement: str, **params: Any) -> Any:
    """The first column of the first row of a read-only statement."""
    async with engine.connect() as connection:
        return (await connection.execute(text(statement), params)).scalar_one()


async def database_dump(engine: AsyncEngine) -> str:
    """Every row of every table as JSON text, the way a dump could be searched."""
    parts: list[str] = []
    async with engine.connect() as connection:
        listing = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        for table in sorted(listing.scalars()):
            rows = await connection.execute(
                text(f'SELECT row_to_json(t)::text FROM "{table}" t')
            )
            parts.extend(rows.scalars())
    return "\n".join(parts)


@contextlib.asynccontextmanager
async def log_unprotected(engine: AsyncEngine, client_id: int) -> AsyncIterator[None]:
    """Let a test change one client's evidence_log rows, then put them back.

    The append-only triggers are switched off inside a transaction, which the
    table owner may do. The rows are restored on exit so that the shared test
    database never keeps a broken chain.
    """
    async with engine.connect() as connection:
        result = await connection.execute(SELECT_LOG, {"client_id": client_id})
        saved = [dict(row._mapping) for row in result]
    try:
        yield
    finally:
        async with engine.begin() as connection:
            await connection.execute(DISABLE_TRIGGERS)
            await connection.execute(DELETE_LOG, {"client_id": client_id})
            for row in saved:
                payload = row["payload"]
                # A raw SELECT may give the JSONB column back as text.
                if not isinstance(payload, str):
                    payload = json.dumps(payload)
                await connection.execute(INSERT_LOG, {**row, "payload": payload})
            await connection.execute(ENABLE_TRIGGERS)


async def change_log(engine: AsyncEngine, statement: str, **params: Any) -> None:
    """Run a statement on evidence_log with the append-only triggers switched off."""
    async with engine.begin() as connection:
        await connection.execute(DISABLE_TRIGGERS)
        await connection.execute(text(statement), params)
        await connection.execute(ENABLE_TRIGGERS)
