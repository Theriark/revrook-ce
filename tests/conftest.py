"""Shared test setup: synthetic settings, a database URL and a network guard.

Tests never reach the real network. The guard allows loopback and the host of
DATABASE_URL (the PostgreSQL service container or the compose database).
"""

import base64
import contextlib
import functools
import ipaddress
import json
import os
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import make_engine
from app.main import create_app
from app.settings import Settings, load_settings
from helpers import FakeClock
from tools import sensitivity

ROOT = Path(__file__).resolve().parent.parent
# Tables a test may empty. audit_event and evidence_log are append-only: the
# database rejects TRUNCATE on them, so tests filter their rows instead.
DATA_TABLES = (
    "worker_heartbeat",
    "schedule",
    "report_export",
    "exception_record",
    "control_result",
    "snapshot",
    "fact",
    "import_profile",
    "evidence_revision",
    "evidence_item",
    "client",
    "setting",
    "api_token",
    "app_user",
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"


class NetworkBlockedError(RuntimeError):
    """A test tried to use the real network."""


def make_fernet_key() -> str:
    """The all-zero Fernet key: valid in shape, protects nothing."""
    return base64.urlsafe_b64encode(bytes(32)).decode()


@functools.cache
def allowed_hosts() -> frozenset[str]:
    allowed = set(LOOPBACK_HOSTS)
    url = os.environ.get("DATABASE_URL")
    host = urlparse(url).hostname if url else None
    if host:
        allowed.add(host)
        with contextlib.suppress(OSError):
            allowed.update(socket.gethostbyname_ex(host)[2])
    return frozenset(allowed)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stops every attempt to leave the machine; the value lists what it stopped.

    A library may catch the error (dnspython turns it into a failed lookup), so a
    test that must be sure a packet was refused reads the list of blocked hosts.
    """
    allowed = allowed_hosts()
    blocked: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_getaddrinfo = socket.getaddrinfo

    def check_address(family: int, address: Any) -> None:
        if family in (socket.AF_INET, socket.AF_INET6) and address[0] not in allowed:
            blocked.append(address[0])
            raise NetworkBlockedError(
                f"real network access is blocked in tests: {address[0]}"
            )

    def connect(self: socket.socket, address: Any) -> None:
        check_address(self.family, address)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check_address(self.family, address)
        return real_connect_ex(self, address)

    def sendto(self: socket.socket, data: Any, *args: Any) -> int:
        # sendto(data, address) or sendto(data, flags, address)
        check_address(self.family, args[-1])
        return real_sendto(self, data, *args)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, str) and host not in allowed and not _is_ip_literal(host):
            blocked.append(host)
            raise NetworkBlockedError(
                f"real name resolution is blocked in tests: {host}"
            )
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return blocked


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """Print the sensitivity harness result at the end of the run (phase 5).

    The harness test writes build/sensitivity-report.json; the correlation with equal
    weights is shown here so that it is in the log of the run, passed or not.
    """
    path = sensitivity.DEFAULT_REPORT
    if not path.is_file():
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    terminalreporter.write_sep("-", "sensitivity harness (docs/scoring.md)")
    terminalreporter.write_line(sensitivity.summary(report))


@pytest.fixture
def env() -> dict[str, str]:
    """A valid environment. DATABASE_URL is real in CI, unreachable otherwise."""
    return {
        "DATABASE_URL": os.environ.get("DATABASE_URL") or UNREACHABLE_DATABASE_URL,
        "SECRET_KEY": "test-only-secret-key-0123456789",
        "FERNET_KEY": make_fernet_key(),
    }


@pytest.fixture
def settings(env: dict[str, str]) -> Settings:
    return load_settings(env)


@pytest.fixture
def database_url() -> str:
    """The PostgreSQL URL for database tests; they are skipped without it."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set; the PostgreSQL tests need it")
    return url


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """The test database brought to the newest revision (skipped without one)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set; the PostgreSQL tests need it")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return url


@pytest.fixture
async def db_engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """An engine on the migrated database with every data table emptied."""
    engine = make_engine(migrated_database)
    async with engine.begin() as connection:
        statement = "TRUNCATE " + ", ".join(DATA_TABLES) + " CASCADE"
        await connection.execute(text(statement))
    yield engine
    await engine.dispose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def web_app(settings: Settings, db_engine: AsyncEngine, clock: FakeClock) -> FastAPI:
    return create_app(settings, engine=db_engine, clock=clock)


@pytest.fixture
async def client(web_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=web_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        yield http_client
