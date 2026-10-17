"""The per-token sliding-window rate limit."""

from app.ratelimit import SlidingWindowLimiter


class Ticker:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_the_limit_then_refuses_with_a_retry_time() -> None:
    ticker = Ticker()
    limiter = SlidingWindowLimiter(3, 60.0, clock=ticker)
    for _ in range(3):
        assert limiter.check("token-a") is None
    ticker.now += 20
    retry = limiter.check("token-a")
    assert retry is not None
    assert 39.9 < retry <= 40.0


def test_a_slot_frees_when_the_oldest_hit_leaves_the_window() -> None:
    ticker = Ticker()
    limiter = SlidingWindowLimiter(2, 60.0, clock=ticker)
    assert limiter.check("k") is None
    ticker.now += 30
    assert limiter.check("k") is None
    assert limiter.check("k") is not None
    ticker.now += 30
    assert limiter.check("k") is None
    assert limiter.check("k") is not None


def test_keys_are_counted_separately() -> None:
    limiter = SlidingWindowLimiter(1, 60.0, clock=Ticker())
    assert limiter.check("one") is None
    assert limiter.check("two") is None
    assert limiter.check("one") is not None
