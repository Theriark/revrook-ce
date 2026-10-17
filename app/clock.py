"""Time source. Code that needs the time takes a Clock so tests can fix it."""

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    """The current time as an aware UTC datetime."""
    return datetime.now(UTC)
