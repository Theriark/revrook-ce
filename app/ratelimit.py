"""In-memory sliding-window rate limit (per process)."""

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """Allows at most `limit` hits per key in any `window` seconds.

    State lives in this process only: with several web processes each one
    applies its own limit. Keys are expected to be few (valid API tokens).
    """

    def __init__(
        self,
        limit: int,
        window: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """Record a hit. None when allowed, else the seconds until a slot frees."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return max(self._window - (now - hits[0]), 0.0)
        hits.append(now)
        return None
