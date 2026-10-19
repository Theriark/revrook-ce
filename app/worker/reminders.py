"""Expiry reminders: which evidence is about to go stale, and the message about it.

Only the newest item of each source of each client counts: when the MSP has refreshed
an export, the old one does not nag. An item has a reminder threshold at 30 days, 7
days and 0 days (the day it goes stale) before `expires_at`
(`app.evidence.expiry.REMINDER_THRESHOLD_DAYS`). A reminder is sent once per
threshold crossing: the row (item, threshold) of `reminder_sent` is inserted before
the message goes out, and the primary key refuses a second insert, so two runs, two
workers or a retry cannot send the same reminder twice. When the message cannot be
sent the rows are removed again and the next run tries once more. `sent_at` is the
time the rows were claimed. A renewal (a revision that moves `expires_at`) starts a
new cycle: a row sent more than its threshold plus a day before `expires_at` belongs
to an earlier expiry and is dropped, so the next year is reminded again. A correction
that keeps the same expiry does not clear anything.

An item seen for the first time at 5 days left has crossed 30 and 7: one line, with
both thresholds recorded. A run sends one message with every client, not one per
item, and the message holds client names, source names and dates only.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.expiry import days_left, reminder_thresholds_due
from app.models import Client, EvidenceItem, ReminderSent

SUBJECT = "revrook: evidence is about to expire or has expired"
MAX_LINES = 200
FOOTER = (
    "Open revrook, go to the evidence of the client and refresh the export or the "
    "artefact. This message names clients, sources and dates only."
)


@dataclass(frozen=True)
class Reminder:
    """One evidence item with the thresholds it has newly crossed."""

    item_id: int
    client_name: str
    source_code: str
    assurance: str
    expires_at: datetime
    days_left: int
    thresholds: tuple[int, ...]


async def due_reminders(session: AsyncSession, now: datetime) -> list[Reminder]:
    """The items that crossed a threshold that has not been sent yet."""
    newest = await session.execute(
        select(
            EvidenceItem.id,
            EvidenceItem.source_code,
            EvidenceItem.assurance_level,
            EvidenceItem.captured_at,
            EvidenceItem.expires_at,
            Client.name.label("client_name"),
        )
        .join(Client, Client.id == EvidenceItem.client_id)
        .where(Client.archived_at.is_(None))
        .distinct(EvidenceItem.client_id, EvidenceItem.source_code)
        .order_by(
            EvidenceItem.client_id,
            EvidenceItem.source_code,
            EvidenceItem.captured_at.desc(),
            EvidenceItem.id.desc(),
        )
    )
    candidates = [row for row in newest.all() if row.expires_at is not None]
    if not candidates:
        return []
    item_ids = [row.id for row in candidates]
    expiry = {row.id: row.expires_at for row in candidates}
    # A renewal keeps the item and moves its expiry: it starts a new cycle. A
    # threshold is crossed when fewer than threshold + 1 whole days are left (days
    # are rounded down), so it is never sent earlier than that before the expiry. A
    # row with sent_at before that moment was sent for an earlier expiry. It is
    # dropped here (inside the transaction of the claim) and the thresholds of the
    # new expiry can be sent again. A correction that keeps the expiry leaves the
    # rows alone, so nothing is mailed twice.
    sent_rows = await session.execute(
        select(
            ReminderSent.item_id, ReminderSent.threshold_days, ReminderSent.sent_at
        ).where(ReminderSent.item_id.in_(item_ids))
    )
    sent: set[tuple[int, int]] = set()
    old: list[tuple[int, int]] = []
    for item_id, threshold, sent_at in sent_rows.all():
        if sent_at < expiry[item_id] - timedelta(days=threshold + 1):
            old.append((item_id, threshold))
        else:
            sent.add((item_id, threshold))
    if old:
        await session.execute(
            delete(ReminderSent).where(
                tuple_(ReminderSent.item_id, ReminderSent.threshold_days).in_(old)
            )
        )
    reminders: list[Reminder] = []
    for row in candidates:
        crossed = reminder_thresholds_due(row.expires_at, now)
        lifetime = (row.expires_at - row.captured_at).days
        # A threshold counts only when it is under half the life of the item: a
        # 30 day reminder on an export that is stale after 35 days is just noise.
        fresh = tuple(
            t for t in crossed if 2 * t < lifetime and (row.id, t) not in sent
        )
        if fresh:
            reminders.append(
                Reminder(
                    item_id=row.id,
                    client_name=row.client_name,
                    source_code=row.source_code,
                    assurance=row.assurance_level,
                    expires_at=row.expires_at,
                    days_left=days_left(row.expires_at, now),
                    thresholds=fresh,
                )
            )
    return reminders


async def claim_reminders(
    session: AsyncSession, reminders: list[Reminder], now: datetime
) -> list[Reminder]:
    """Record the thresholds as sent. Returns what this call claimed, no more.

    A row that already exists (another run claimed it first) is not claimed again.
    """
    rows = [
        {"item_id": reminder.item_id, "threshold_days": threshold, "sent_at": now}
        for reminder in reminders
        for threshold in reminder.thresholds
    ]
    if not rows:
        return []
    inserted = await session.execute(
        insert(ReminderSent)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(ReminderSent.item_id, ReminderSent.threshold_days)
    )
    won: defaultdict[int, list[int]] = defaultdict(list)
    for item_id, threshold in inserted.all():
        won[item_id].append(threshold)
    claimed: list[Reminder] = []
    for reminder in reminders:
        mine = tuple(t for t in reminder.thresholds if t in won[reminder.item_id])
        if mine:
            claimed.append(
                Reminder(
                    reminder.item_id,
                    reminder.client_name,
                    reminder.source_code,
                    reminder.assurance,
                    reminder.expires_at,
                    reminder.days_left,
                    mine,
                )
            )
    return claimed


async def release_reminders(session: AsyncSession, reminders: list[Reminder]) -> None:
    """Take the claims back, because the message could not be sent."""
    pairs = [
        (reminder.item_id, threshold)
        for reminder in reminders
        for threshold in reminder.thresholds
    ]
    if pairs:
        await session.execute(
            delete(ReminderSent).where(
                tuple_(ReminderSent.item_id, ReminderSent.threshold_days).in_(pairs)
            )
        )


def _when(reminder: Reminder) -> str:
    day = reminder.expires_at.strftime("%Y-%m-%d")
    left = reminder.days_left
    if left < 0:
        ago = -left
        return f"went stale on {day} ({ago} day{'s' if ago != 1 else ''} ago)"
    if left == 0:
        return f"goes stale today, {day}"
    return f"goes stale on {day} (in {left} day{'s' if left != 1 else ''})"


def compose_message(reminders: list[Reminder]) -> str:
    """The text of the one message of a run, grouped by client."""
    by_client: defaultdict[str, list[Reminder]] = defaultdict(list)
    for reminder in sorted(reminders, key=lambda r: (r.client_name, r.expires_at)):
        by_client[reminder.client_name].append(reminder)
    lines = [SUBJECT, ""]
    shown = 0
    for client_name, items in by_client.items():
        lines.append(f"Client: {client_name}")
        for item in items:
            if shown >= MAX_LINES:
                break
            lines.append(f"  - {item.source_code} ({item.assurance}) {_when(item)}")
            shown += 1
        lines.append("")
    if len(reminders) > shown:
        lines.append(f"... and {len(reminders) - shown} more items.")
        lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines) + "\n"
