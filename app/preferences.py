"""Settings of the installation that a person can change.

The MSP name (phase 9) is printed on every report. The reminder address (phase 10)
is where the expiry reminders go; the mail relay itself is set in the environment.
"""

import re
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.models import Setting
from app.reports.completeness import MAX_SHORT
from app.textcheck import control_character

MSP_NAME_KEY = "msp_name"
REMINDER_KEY = "reminder_recipient"
MAX_EMAIL_LENGTH = 254
# One plain address: letters, digits and a few signs, an @ and a dotted domain. No
# space, quote, comma or angle bracket, so it cannot add a recipient or a header.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


async def get_msp_name(session: AsyncSession) -> str:
    """The name printed on the cover of every report; empty until it is set."""
    row = await session.get(Setting, MSP_NAME_KEY)
    if row is None:
        return ""
    name = row.value.get("name")
    return name if isinstance(name, str) else ""


async def _save(
    session: AsyncSession,
    key: str,
    value: dict[str, str],
    user_id: int | None,
    now: datetime,
) -> None:
    await session.execute(
        insert(Setting)
        .values(key=key, value=value, updated_by_id=user_id, updated_at=now)
        .on_conflict_do_update(
            index_elements=[Setting.key],
            set_={"value": value, "updated_by_id": user_id, "updated_at": now},
        )
    )


async def set_msp_name(
    session: AsyncSession, name: str, *, user_id: int | None, now: datetime
) -> str:
    """Save the MSP name. Raises ValueError with a readable message when it is bad."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("The MSP name cannot be empty.")
    if len(cleaned) > MAX_SHORT:
        raise ValueError(f"The MSP name is longer than {MAX_SHORT} characters.")
    if control_character(cleaned) is not None:
        raise ValueError("The MSP name contains a control character.")
    await _save(session, MSP_NAME_KEY, {"name": cleaned}, user_id, now)
    add_audit_event(
        session,
        "settings.msp_name",
        actor_user_id=user_id,
        target_type="setting",
        target_id=MSP_NAME_KEY,
    )
    return cleaned


async def get_reminder_recipient(session: AsyncSession) -> str | None:
    """The address the expiry reminders go to; None until one is set."""
    row = await session.get(Setting, REMINDER_KEY)
    if row is None:
        return None
    address = row.value.get("address")
    if isinstance(address, str) and EMAIL.fullmatch(address):
        return address
    return None


async def set_reminder_recipient(
    session: AsyncSession, address: str, *, user_id: int | None, now: datetime
) -> str | None:
    """Save the reminder address; an empty one turns the reminders off.

    Raises ValueError with a readable message when the address is not one plain
    address. The address itself is never written to the audit trail.
    """
    cleaned = address.strip()
    too_long = len(cleaned) > MAX_EMAIL_LENGTH
    if cleaned and (too_long or EMAIL.fullmatch(cleaned) is None):
        raise ValueError("The reminder address must be one plain email address.")
    await _save(session, REMINDER_KEY, {"address": cleaned}, user_id, now)
    add_audit_event(
        session,
        "settings.reminder_recipient",
        actor_user_id=user_id,
        target_type="setting",
        target_id=REMINDER_KEY,
        detail={"set": bool(cleaned)},
    )
    return cleaned or None
