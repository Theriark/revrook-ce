"""Several tools of one source: which files of a device, backup or network source count.

A client's network evidence often comes from several tools (the office firewall and a
cloud). A file of one of these sources may name the tool that wrote it (the `tool`
column, kept in the file's summary fact); the newest file of each tool counts, a file
that names none being one more tool. The checks (app/posture.py), the Sources table of
the evidence page (app/ui/viewmodels.py) and the expiry reminders
(app/worker/reminders.py) all choose files with `per_tool`.
"""

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.assurance import Assurance
from app.evidence.expiry import DEFAULT_MAX_AGE_DAYS
from app.models import Fact

TOOL_SOURCES = frozenset({"device-inventory", "backup-export", "network-export"})
# A tool's file counts while it is at most this much older than the newest file of
# its source, so a tool that is no longer used drops out.
TOOL_WINDOW = timedelta(days=DEFAULT_MAX_AGE_DAYS[Assurance.AUTOMATIC_EXPORT])


class Dated(Protocol):
    @property
    def source_code(self) -> str: ...
    @property
    def captured_at(self) -> datetime: ...


def per_tool[T: Dated](candidates: Sequence[tuple[T, str | None]]) -> list[T]:
    """The newest item of each tool of a source, from (item, tool) pairs that are
    newest first within each source. A file that names no tool is one more tool; an
    item more than TOOL_WINDOW older than the newest item of its source is left out.
    """
    newest: dict[str, datetime] = {}
    seen: set[tuple[str, str | None]] = set()
    chosen: list[T] = []
    for item, tool in candidates:
        first = newest.setdefault(item.source_code, item.captured_at)
        key = (item.source_code, tool)
        if key in seen or first - item.captured_at > TOOL_WINDOW:
            continue
        seen.add(key)
        chosen.append(item)
    return chosen


async def tools_of(
    session: AsyncSession, item_ids: Collection[int]
) -> dict[int, str | None]:
    """The tool each of these evidence items names (None when its file names none)."""
    if not item_ids:
        return {}
    rows = await session.execute(
        select(Fact.evidence_item_id, Fact.value).where(
            Fact.evidence_item_id.in_(list(item_ids)),
            Fact.fact_key.endswith(".summary"),
        )
    )
    found: dict[int, str | None] = {item_id: None for item_id in item_ids}
    for item_id, value in rows:
        tool = value.get("tool") if isinstance(value, dict) else None
        found[item_id] = tool if isinstance(tool, str) else None
    return found
