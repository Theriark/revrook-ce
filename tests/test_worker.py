import asyncio
import logging

import pytest

from app.db import WORKER_LOCK_KEY, advisory_lock, make_engine
from app.settings import Settings, load_settings
from app.worker import run_worker

UNREACHABLE = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"


async def run_briefly(task_args: dict[str, object], seconds: float = 0.3) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(run_worker(stop=stop, interval=0.05, **task_args))  # type: ignore[arg-type]
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_worker_takes_the_advisory_lock_and_stops_on_request(
    settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="revrook.worker")
    engine = make_engine(database_url)
    try:
        await run_briefly({"settings": settings, "engine": engine})
    finally:
        await engine.dispose()
    assert "advisory lock held" in caplog.text


async def test_second_worker_stands_by_while_the_lock_is_taken(
    settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="revrook.worker")
    holder = make_engine(database_url)
    worker_engine = make_engine(database_url)
    try:
        async with advisory_lock(holder, WORKER_LOCK_KEY) as taken:
            assert taken
            await run_briefly({"settings": settings, "engine": worker_engine})
    finally:
        await holder.dispose()
        await worker_engine.dispose()
    assert "advisory lock busy; standing by" in caplog.text
    assert "advisory lock held" not in caplog.text


async def test_worker_keeps_retrying_when_the_database_is_down(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="revrook.worker")
    down = load_settings({**env, "DATABASE_URL": UNREACHABLE})
    # No engine passed: the worker builds and disposes its own.
    await run_briefly({"settings": down})
    assert "database unavailable; retrying" in caplog.text
