"""Background worker. Phase 0 only holds the advisory lock and idles.

Schedules, reminders and retention arrive in phase 10.
"""

import asyncio
import contextlib
import logging
import signal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import WORKER_LOCK_KEY, advisory_lock, make_engine
from app.settings import Settings

logger = logging.getLogger("revrook.worker")


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    """Sleep up to the given time, waking early when stop is set."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run_worker(
    settings: Settings,
    stop: asyncio.Event,
    interval: float = 5.0,
    engine: AsyncEngine | None = None,
) -> None:
    """Run until stop is set. Only one worker at a time holds the lock."""
    db_engine = engine or make_engine(settings.database_url)
    try:
        while not stop.is_set():
            try:
                async with advisory_lock(db_engine, WORKER_LOCK_KEY) as acquired:
                    if acquired:
                        logger.info("advisory lock held; no schedules yet")
                    else:
                        logger.info("advisory lock busy; standing by")
                    await _sleep(stop, interval)
            except (SQLAlchemyError, OSError):
                logger.warning("database unavailable; retrying")
                await _sleep(stop, interval)
    finally:
        if engine is None:
            await db_engine.dispose()


def serve(settings: Settings) -> None:  # pragma: no cover
    """Run the worker in this process until SIGTERM or SIGINT."""

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await run_worker(settings, stop)

    asyncio.run(main())
