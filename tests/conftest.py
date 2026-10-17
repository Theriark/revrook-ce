"""Shared test setup: synthetic settings, a database URL and a network guard.

Tests never reach the real network. The guard allows loopback and the host of
DATABASE_URL (the PostgreSQL service container or the compose database).
"""

import base64
import contextlib
import functools
import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse

import pytest

from app.settings import Settings, load_settings

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
def forbid_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = allowed_hosts()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def check_address(family: int, address: Any) -> None:
        if family in (socket.AF_INET, socket.AF_INET6) and address[0] not in allowed:
            raise NetworkBlockedError(
                f"real network access is blocked in tests: {address[0]}"
            )

    def connect(self: socket.socket, address: Any) -> None:
        check_address(self.family, address)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check_address(self.family, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, str) and host not in allowed and not _is_ip_literal(host):
            raise NetworkBlockedError(
                f"real name resolution is blocked in tests: {host}"
            )
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


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
