"""Writing to the append-only audit_event table."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


def add_audit_event(
    session: AsyncSession,
    action: str,
    *,
    actor_user_id: int | None = None,
    target_type: str | None = None,
    target_id: int | str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Queue one audit row in the caller's transaction.

    The detail holds reasons and counts only: never a password, token, key or
    personal identifier. Rows can be inserted, never changed or deleted.
    """
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id),
            detail=detail or {},
        )
    )
