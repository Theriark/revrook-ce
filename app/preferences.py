"""Settings of the installation that a person can change.

The MSP name (phase 9) is printed on every report. The reminder address (phase 10)
is where the expiry reminders go; the mail relay itself is set in the environment.
"""

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.models import Setting
from app.reports.completeness import MAX_SHORT
from app.textcheck import control_character

MSP_NAME_KEY = "msp_name"
REMINDER_KEY = "reminder_recipient"
LOGO_KEY = "msp_logo"
MAX_LOGO_BYTES = 200 * 1024
# A picture file only (never SVG, which can carry script): the caller names the
# type by the first bytes of the file, not by what the browser said.
LOGO_TYPES = ("image/png", "image/jpeg", "image/webp")
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


@dataclass(frozen=True)
class Logo:
    """The logo of the MSP: a picture file and its media type."""

    media_type: str
    data: bytes


async def get_logo(session: AsyncSession) -> Logo | None:
    """The logo printed on the cover of every report; None until one is set."""
    row = await session.get(Setting, LOGO_KEY)
    if row is None:
        return None
    media_type, encoded = row.value.get("type"), row.value.get("data")
    if media_type not in LOGO_TYPES or not isinstance(encoded, str) or not encoded:
        return None
    try:
        return Logo(media_type, base64.b64decode(encoded, validate=True))
    except binascii.Error:
        return None


async def set_logo(
    session: AsyncSession,
    data: bytes,
    media_type: str | None,
    *,
    user_id: int | None,
    now: datetime,
) -> None:
    """Save the logo. Raises ValueError with a readable message when it is bad."""
    if media_type not in LOGO_TYPES or not data:
        raise ValueError("The logo must be a PNG, JPEG or WebP image.")
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError(f"The logo must be at most {MAX_LOGO_BYTES // 1024} KB.")
    value = {"type": media_type, "data": base64.b64encode(data).decode("ascii")}
    await _save(session, LOGO_KEY, value, user_id, now)
    add_audit_event(
        session,
        "settings.msp_logo",
        actor_user_id=user_id,
        target_type="setting",
        target_id=LOGO_KEY,
        detail={"bytes": len(data)},
    )


async def remove_logo(
    session: AsyncSession, *, user_id: int | None, now: datetime
) -> None:
    """Take the logo away: the cover of a report prints the name alone again."""
    await _save(session, LOGO_KEY, {}, user_id, now)
    add_audit_event(
        session,
        "settings.msp_logo",
        actor_user_id=user_id,
        target_type="setting",
        target_id=LOGO_KEY,
        detail={"removed": True},
    )


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
