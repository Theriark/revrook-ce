"""Settings of the installation that a person can change: the MSP name (phase 9)."""

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.models import Setting
from app.reports.completeness import MAX_SHORT
from app.textcheck import control_character

MSP_NAME_KEY = "msp_name"


async def get_msp_name(session: AsyncSession) -> str:
    """The name printed on the cover of every report; empty until it is set."""
    row = await session.get(Setting, MSP_NAME_KEY)
    if row is None:
        return ""
    name = row.value.get("name")
    return name if isinstance(name, str) else ""


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
    value = {"name": cleaned}
    await session.execute(
        insert(Setting)
        .values(key=MSP_NAME_KEY, value=value, updated_by_id=user_id, updated_at=now)
        .on_conflict_do_update(
            index_elements=[Setting.key],
            set_={"value": value, "updated_by_id": user_id, "updated_at": now},
        )
    )
    add_audit_event(
        session,
        "settings.msp_name",
        actor_user_id=user_id,
        target_type="setting",
        target_id=MSP_NAME_KEY,
    )
    return cleaned
