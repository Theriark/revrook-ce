"""The worker heartbeat: a row the worker writes every few seconds, read by the web.

A worker upserts its row in `worker_heartbeat` on every tick. The web role reads the
newest `beat_at`: older than STALE_AFTER means no worker is running, which the pages
show as a banner (a worker stopped is seen within the 3 minutes this allows several
times over) and which `/readyz` reports when ROLE=all.
"""

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import WorkerHeartbeat

# Six missed ticks of five seconds. Well inside the 3 minutes the banner may take.
STALE_AFTER = timedelta(seconds=90)
# A worker that was replaced leaves a row; rows older than this are removed.
KEEP_FOR = timedelta(days=1)
RUNNING = "running"
STALE = "stale"
NEVER = "never"


@dataclass(frozen=True)
class WorkerStatus:
    """What the heartbeat table says at one moment."""

    state: str
    last_beat: datetime | None
    age_seconds: float | None
    workers: int

    @property
    def stale(self) -> bool:
        return self.state == STALE

    @property
    def running(self) -> bool:
        return self.state == RUNNING


def worker_id() -> str:
    """A name for this worker process: the host and the process id."""
    return f"{socket.gethostname()}-{os.getpid()}"[:64]


async def beat(
    session_factory: async_sessionmaker[AsyncSession],
    name: str,
    now: datetime,
    detail: Mapping[str, Any],
) -> None:
    """Record that the worker `name` is alive at `now`; drop rows of old workers."""
    values = dict(detail)
    async with session_factory() as session, session.begin():
        await session.execute(
            insert(WorkerHeartbeat)
            .values(worker_id=name, beat_at=now, detail=values)
            .on_conflict_do_update(
                index_elements=[WorkerHeartbeat.worker_id],
                set_={"beat_at": now, "detail": values},
            )
        )
        await session.execute(
            delete(WorkerHeartbeat).where(WorkerHeartbeat.beat_at < now - KEEP_FOR)
        )


async def read_status(session: AsyncSession, now: datetime) -> WorkerStatus:
    """Whether a worker is running at `now`, from the newest heartbeat."""
    newest = (
        await session.execute(select(func.max(WorkerHeartbeat.beat_at)))
    ).scalar_one()
    if newest is None:
        return WorkerStatus(NEVER, None, None, 0)
    fresh = (
        await session.execute(
            select(func.count())
            .select_from(WorkerHeartbeat)
            .where(WorkerHeartbeat.beat_at >= now - STALE_AFTER)
        )
    ).scalar_one()
    age = max((now - newest).total_seconds(), 0.0)
    state = RUNNING if now - newest <= STALE_AFTER else STALE
    return WorkerStatus(state, newest, age, int(fresh))
