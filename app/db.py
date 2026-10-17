"""Database access: async engine, declarative base and an advisory lock helper."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# Application-wide advisory lock key: only one worker may hold it at a time.
WORKER_LOCK_KEY = 7_262_001


class Base(DeclarativeBase):
    """Declarative base for every table; the models arrive in phase 1."""


def make_engine(url: str) -> AsyncEngine:
    """Create the async engine. It opens no connection until first use."""
    return create_async_engine(url, pool_pre_ping=True)


async def check_database(engine: AsyncEngine, timeout: float = 5.0) -> bool:
    """True when a trivial query succeeds within the timeout."""
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        # TimeoutError is an OSError, so a timeout lands here too.
        return False
    return True


@asynccontextmanager
async def advisory_lock(engine: AsyncEngine, key: int) -> AsyncIterator[bool]:
    """Try to take a session-level advisory lock; yield whether it was taken.

    The lock is released on exit. It is also released by the server if the
    connection dies.
    """
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        )
        acquired = bool(result.scalar_one())
        try:
            yield acquired
        finally:
            if acquired:
                with contextlib.suppress(SQLAlchemyError, OSError):
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
