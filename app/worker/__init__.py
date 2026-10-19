"""Background worker: the heartbeat, the scheduler and the jobs of phase 10.

Every tick the worker writes its heartbeat. The worker that holds the advisory lock
(only one does) also starts new schedules, runs the ones that are due and sends the
optional outbound heartbeat. A worker that does not get the lock stands by and takes
over when the other one stops.
"""

import asyncio
import contextlib
import logging
import signal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import __version__
from app.clock import Clock, utcnow
from app.db import WORKER_LOCK_KEY, advisory_lock, make_engine
from app.settings import Settings
from app.worker.heartbeat import beat, worker_id
from app.worker.jobs import JobContext, build_jobs, make_job_context
from app.worker.ping import Pinger
from app.worker.scheduler import ensure_default_schedules, run_due, start_unscheduled

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
    clock: Clock = utcnow,
    context: JobContext | None = None,
) -> None:
    """Run until stop is set. Only one worker at a time holds the lock."""
    db_engine = engine or make_engine(settings.database_url)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    jobs = build_jobs(context or make_job_context(settings, factory))
    pinger = Pinger(settings.heartbeat_url)
    name = worker_id()
    leader: bool | None = None
    try:
        while not stop.is_set():
            try:
                async with advisory_lock(db_engine, WORKER_LOCK_KEY) as acquired:
                    now = clock()
                    detail = {
                        "version": __version__,
                        "role": settings.role,
                        "leader": acquired,
                    }
                    await beat(factory, name, now, detail)
                    if acquired:
                        if leader is not True:
                            logger.info("advisory lock held; running schedules")
                            await ensure_default_schedules(factory, now)
                        leader = True
                        await start_unscheduled(factory, now)
                        await run_due(factory, jobs, now)
                        await pinger.ping_if_due()
                    else:
                        if leader is not False:
                            logger.info("advisory lock busy; standing by")
                        leader = False
                    await _sleep(stop, interval)
            except (SQLAlchemyError, OSError):
                logger.warning("database unavailable; retrying")
                leader = None
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
