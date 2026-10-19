"""Drafts: the notes a technician is writing, saved as they type.

One row of the `setting` table per client (`draft_key`) holds what has not been
exported yet: the notes for each control, the plan for next quarter, who owns each
topic, which topics the insurer of the client asks about and who prepared the report.
Every change is saved at once (the pages post on each change), so a session that
ends loses nothing typed before it ended. The draft is deleted with its client.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.locking import lock_client
from app.models import Setting, draft_key
from app.reports.completeness import MAX_LIST, MAX_SHORT, MAX_TEXT
from app.reports.topics import TOPIC_KEYS
from app.reports.view import Finding
from app.textcheck import control_character, normalise_breaks


class DraftError(ValueError):
    """A note or detail cannot be saved: too long, or not text a report can print."""


@dataclass(frozen=True)
class Draft:
    """What is saved for one client."""

    findings: Mapping[str, Finding] = field(default_factory=dict)
    plan: tuple[str, ...] = ()
    owners: Mapping[str, str] = field(default_factory=dict)
    asked: frozenset[str] | None = None
    prepared_by: str = ""
    saved_at: datetime | None = None


def _texts(value: object) -> dict[str, str]:
    found: dict[str, str] = {}
    if isinstance(value, dict):
        for key, text in value.items():
            if isinstance(key, str) and isinstance(text, str):
                found[key] = text
    return found


def _finding(value: object) -> Finding:
    parts = _texts(value)
    return Finding(
        did=parts.get("did", ""),
        recommend=parts.get("recommend", ""),
        need=parts.get("need", ""),
        by_when=parts.get("by_when", ""),
    )


def _findings(value: object) -> dict[str, Finding]:
    found: dict[str, Finding] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                found[key] = _finding(item)
    return found


def _lines(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(line for line in value if isinstance(line, str))


def _topics(value: object) -> frozenset[str] | None:
    if not isinstance(value, list):
        return None
    return frozenset(key for key in value if isinstance(key, str))


def _draft_of(value: Mapping[str, Any], saved_at: datetime | None) -> Draft:
    prepared = value.get("prepared_by")
    return Draft(
        findings=_findings(value.get("findings")),
        plan=_lines(value.get("plan")),
        owners=_texts(value.get("owners")),
        asked=_topics(value.get("asked")),
        prepared_by=prepared if isinstance(prepared, str) else "",
        saved_at=saved_at,
    )


async def load_draft(session: AsyncSession, client_id: int) -> Draft:
    """The draft of a client; an empty one when nothing was saved yet."""
    row = await session.get(Setting, draft_key(client_id))
    if row is None:
        return Draft()
    return _draft_of(row.value, row.updated_at)


def check_text(label: str, value: str, limit: int) -> str:
    """The text without blank space around it; DraftError if it cannot be saved.

    Line breaks are counted as LF, as the browser counts them for maxlength.
    """
    cleaned = normalise_breaks(value).strip()
    if len(cleaned) > limit:
        raise DraftError(f"{label} is longer than {limit} characters.")
    if control_character(cleaned, allow_breaks=True) is not None:
        raise DraftError(f"{label} contains a control character.")
    return cleaned


async def _row(session: AsyncSession, client_id: int) -> Setting:
    """The draft row of a client, created if needed, under the client's lock.

    The lock serialises every save of one client, so two autosaves in flight cannot
    overwrite each other, and a client being deleted is waited for (ClientNotFoundError
    afterwards) instead of getting a draft nobody will delete.
    """
    await lock_client(session, client_id)
    row = await session.get(Setting, draft_key(client_id))
    if row is None:
        row = Setting(key=draft_key(client_id), value={})
        session.add(row)
    return row


def _write(
    row: Setting, value: dict[str, Any], user_id: int | None, now: datetime
) -> datetime:
    row.value = value
    row.updated_by_id = user_id
    row.updated_at = now
    return now


async def save_finding(
    session: AsyncSession,
    client_id: int,
    control_id: str,
    finding: Finding,
    *,
    user_id: int | None,
    now: datetime,
) -> datetime:
    """Save the four notes of one control; empty notes remove the entry."""
    parts = {
        "did": check_text("What we did", finding.did, MAX_TEXT),
        "recommend": check_text("What we recommend", finding.recommend, MAX_TEXT),
        "need": check_text("What we need from you", finding.need, MAX_TEXT),
        "by_when": check_text("By when", finding.by_when, MAX_TEXT),
    }
    row = await _row(session, client_id)
    value = dict(row.value)
    findings = dict(value.get("findings") or {})
    if any(parts.values()):
        findings[control_id] = parts
    else:
        findings.pop(control_id, None)
    value["findings"] = findings
    return _write(row, value, user_id, now)


async def save_details(
    session: AsyncSession,
    client_id: int,
    *,
    plan_text: str,
    owners: Mapping[str, str],
    asked: Collection[str],
    prepared_by: str,
    user_id: int | None,
    now: datetime,
) -> datetime:
    """Save the plan, the topic owners, the topics asked about and the preparer."""
    lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
    if len(lines) > MAX_LIST:
        raise DraftError(f"The plan has more than {MAX_LIST} lines.")
    plan = [check_text("A line of the plan", line, MAX_TEXT) for line in lines]
    cleaned_owners: dict[str, str] = {}
    for key, name in owners.items():
        if key not in TOPIC_KEYS:
            raise DraftError("An owner was given for something that is not a topic.")
        owner = check_text("A topic owner", name, MAX_SHORT)
        if owner:
            cleaned_owners[key] = owner
    for key in asked:
        if key not in TOPIC_KEYS:
            raise DraftError("A topic that is not part of the pack was chosen.")
    preparer = check_text("The name of the preparer", prepared_by, MAX_SHORT)
    row = await _row(session, client_id)
    value = dict(row.value)
    value["plan"] = plan
    value["owners"] = cleaned_owners
    value["asked"] = sorted(set(asked))
    value["prepared_by"] = preparer
    return _write(row, value, user_id, now)
