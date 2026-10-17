"""Database driver spike: SQLAlchemy async on asyncpg with Alembic and advisory locks.

These tests need PostgreSQL 16 (DATABASE_URL) and are skipped without it.
The outcome is recorded in docs/licences.md.
"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app.db import WORKER_LOCK_KEY, advisory_lock, check_database, make_engine

ROOT = Path(__file__).resolve().parent.parent


def alembic(database_url: str, *args: str) -> str:
    """Run an Alembic command in a subprocess; return its combined output."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{output}"
    return output


def test_migrations_upgrade_check_downgrade_upgrade(database_url: str) -> None:
    alembic(database_url, "upgrade", "head")
    assert "0001" in alembic(database_url, "current")
    assert "No new upgrade operations detected" in alembic(database_url, "check")
    alembic(database_url, "downgrade", "-1")
    assert "0001" not in alembic(database_url, "current")
    alembic(database_url, "upgrade", "head")
    assert "0001" in alembic(database_url, "current")


async def test_asyncpg_driver_connects_to_postgresql_16(database_url: str) -> None:
    engine = make_engine(database_url)
    try:
        assert engine.dialect.driver == "asyncpg"
        async with engine.connect() as connection:
            result = await connection.execute(text("SHOW server_version_num"))
            version = int(result.scalar_one())
        assert version >= 160000
        assert await check_database(engine)
    finally:
        await engine.dispose()


async def test_advisory_lock_is_exclusive_and_released(database_url: str) -> None:
    engine = make_engine(database_url)
    try:
        async with advisory_lock(engine, WORKER_LOCK_KEY) as first:
            assert first
            async with advisory_lock(engine, WORKER_LOCK_KEY) as second:
                assert not second
        async with advisory_lock(engine, WORKER_LOCK_KEY) as third:
            assert third
    finally:
        await engine.dispose()
