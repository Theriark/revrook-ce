"""The live state of one client: its newest evidence, run through the check engine.

Nothing here is stored. The newest automatic export of every source is read with its
facts (for a device, backup or network source, the newest export of each tool), the
open exceptions are attached, and the check engine decides every control
(`evaluate_all`). The scoring inputs of that state are a `SnapshotInput`, the same
thing a stored snapshot is made of, so a page of the application and a report show
the same numbers: `build_view` turns the bytes of a snapshot into the view that both
of them use.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checks.engine import evaluate_all
from app.checks.library import Library
from app.checks.lifecycle import load_lifecycle
from app.checks.model import ControlResult, Evidence, SourceFacts
from app.evidence.errors import ClientNotFoundError
from app.evidence.tools import TOOL_SOURCES, TOOL_WINDOW, per_tool, tools_of
from app.exceptions import ExceptionEntry
from app.models import Client, EvidenceItem, ExceptionRecord, Fact
from app.reports.view import ReportContext, ReportError, ReportView, build_view
from app.scoring.snapshot import (
    EvidenceRef,
    SnapshotInput,
    render_snapshot,
    snapshot_input,
)

AUTOMATIC_EXPORT = "automatic-export"


@dataclass(frozen=True)
class LiveClient:
    """One client at one moment: the check results and the scoring inputs."""

    client_id: int
    name: str
    as_of: datetime
    results: Mapping[str, ControlResult]
    snapshot: SnapshotInput
    exceptions: tuple[ExceptionEntry, ...]


async def open_exceptions(
    session: AsyncSession, client_id: int
) -> tuple[ExceptionEntry, ...]:
    """The exceptions of the client that are not closed, oldest review date first."""
    rows = await session.execute(
        select(ExceptionRecord)
        .where(
            ExceptionRecord.client_id == client_id,
            ExceptionRecord.closed_at.is_(None),
        )
        .order_by(ExceptionRecord.review_date, ExceptionRecord.id)
    )
    return tuple(
        ExceptionEntry(
            control_id=row.control_id,
            owner=row.owner,
            reason=row.reason,
            compensating_control=row.compensating_control,
            review_date=row.review_date,
        )
        for row in rows.scalars()
    )


async def newest_items(session: AsyncSession, client_id: int) -> list[EvidenceItem]:
    """The automatic exports of the client the checks read (see per_tool)."""
    newest = await session.execute(
        select(EvidenceItem)
        .where(
            EvidenceItem.client_id == client_id,
            EvidenceItem.assurance_level == AUTOMATIC_EXPORT,
        )
        .distinct(EvidenceItem.source_code)
        .order_by(
            EvidenceItem.source_code,
            EvidenceItem.captured_at.desc(),
            EvidenceItem.id.desc(),
        )
    )
    items = list(newest.scalars())
    since = {
        item.source_code: item.captured_at - TOOL_WINDOW
        for item in items
        if item.source_code in TOOL_SOURCES
    }
    if not since:
        return items
    recent = await session.execute(
        select(EvidenceItem)
        .where(
            EvidenceItem.client_id == client_id,
            EvidenceItem.assurance_level == AUTOMATIC_EXPORT,
            or_(
                *(
                    and_(
                        EvidenceItem.source_code == code, EvidenceItem.captured_at >= at
                    )
                    for code, at in since.items()
                )
            ),
        )
        .order_by(
            EvidenceItem.source_code,
            EvidenceItem.captured_at.desc(),
            EvidenceItem.id.desc(),
        )
    )
    tooled = list(recent.scalars())
    tools = await tools_of(session, [item.id for item in tooled])
    others = [item for item in items if item.source_code not in TOOL_SOURCES]
    return others + per_tool([(item, tools.get(item.id)) for item in tooled])


async def load_sources(
    session: AsyncSession, items: list[EvidenceItem]
) -> dict[str, SourceFacts]:
    """The facts of each of these items, grouped as the check engine reads them."""
    if not items:
        return {}
    rows = await session.execute(
        select(Fact.evidence_item_id, Fact.fact_key, Fact.value)
        .where(Fact.evidence_item_id.in_([item.id for item in items]))
        .order_by(Fact.id)
    )
    grouped: defaultdict[int, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for item_id, key, value in rows:
        grouped[item_id].append((key, value))
    sources: dict[str, SourceFacts] = {}
    for item in items:
        facts = SourceFacts.from_facts(item.captured_at, grouped.get(item.id, []))
        earlier = sources.get(item.source_code)
        sources[item.source_code] = facts if earlier is None else merged(earlier, facts)
    return sources


def merged(first: SourceFacts, other: SourceFacts) -> SourceFacts:
    """Two files of one source read as one: every row, measured from the newer capture.

    An age is then measured from the newest export, so a row of the older file is
    never younger than it is. The summary is the first file's (the checks of the
    TOOL_SOURCES read rows only).
    """
    kinds = {
        kind: first.rows(kind) + other.rows(kind)
        for kind in dict.fromkeys([*first.kinds, *other.kinds])
    }
    captured_at = max(first.captured_at, other.captured_at)
    return SourceFacts(captured_at=captured_at, kinds=kinds, summary=first.summary)


def importer_summary(items: list[EvidenceItem]) -> str:
    """The importer versions the evidence was read with, as a snapshot records them."""
    pairs: set[str] = set()
    for item in items:
        if item.importer_version:
            pairs.add(f"{item.source_code}={item.importer_version}")
    return ",".join(sorted(pairs)) or "none"


async def load_live(
    session: AsyncSession, library: Library, client_id: int, as_of: datetime
) -> LiveClient:
    """Run the check engine over the newest evidence of one client at `as_of`.

    Raises ClientNotFoundError when the client does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise ClientNotFoundError("There is no client with this id.")
    items = await newest_items(session, client_id)
    sources = await load_sources(session, items)
    exceptions = await open_exceptions(session, client_id)
    evidence = Evidence(
        as_of=as_of, sources=sources, exceptions=exceptions, lifecycle=load_lifecycle()
    )
    results = evaluate_all(library, evidence)
    refs = [EvidenceRef(str(item.id), item.sha256) for item in items]
    snapshot = snapshot_input(library, results, as_of, refs, importer_summary(items))
    return LiveClient(
        client_id=client_id,
        name=client.name,
        as_of=as_of,
        results=results,
        snapshot=snapshot,
        exceptions=exceptions,
    )


def view_from(
    data: bytes,
    library: Library,
    context: ReportContext,
    previous: bytes | None = None,
) -> ReportView:
    """The report view of a snapshot; an unreadable earlier snapshot is ignored."""
    try:
        return build_view(data, library, context, previous)
    except ReportError:
        if previous is None:
            raise
        return build_view(data, library, context)


def view_of(
    live: LiveClient,
    library: Library,
    context: ReportContext,
    previous: bytes | None = None,
) -> ReportView:
    """The report view of the live state, as if a snapshot of it had been stored."""
    return view_from(render_snapshot(live.snapshot), library, context, previous)
