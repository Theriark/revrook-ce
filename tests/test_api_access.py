"""API access with bearer tokens: issue, authenticate, revoke and rate limit."""

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth import issue_api_token, revoke_api_token
from app.models import ApiToken, AppUser
from app.ratelimit import SlidingWindowLimiter
from helpers import FakeClock, audit_baseline, audit_since, create_admin


async def issue(engine: AsyncEngine, user_id: int, name: str = "ci") -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        user = await session.get(AppUser, user_id)
        assert user is not None
        return await issue_api_token(session, user, name)


async def load_tokens(engine: AsyncEngine) -> list[ApiToken]:
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(select(ApiToken))).scalars())


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


async def test_a_token_is_stored_only_as_a_hash_and_audited(
    db_engine: AsyncEngine,
) -> None:
    user_id = await create_admin(db_engine)
    baseline = await audit_baseline(db_engine)
    token = await issue(db_engine, user_id, "backup script")
    (stored,) = await load_tokens(db_engine)
    assert stored.name == "backup script"
    assert stored.token_hash != token
    assert token not in stored.token_hash
    assert len(stored.token_hash) == 64
    assert token.startswith(stored.token_prefix)
    assert token != stored.token_prefix
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["api_token.created"]
    assert token not in str(events[0].detail)


async def test_a_valid_token_authenticates_and_records_its_use(
    client: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    user_id = await create_admin(db_engine)
    token = await issue(db_engine, user_id)
    response = await client.get("/api/v1/whoami", headers=bearer(token))
    assert response.status_code == 200
    assert response.json() == {"username": "admin"}
    (stored,) = await load_tokens(db_engine)
    assert stored.last_used_at == clock.now


async def test_a_missing_or_wrong_token_is_401(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    user_id = await create_admin(db_engine)
    token = await issue(db_engine, user_id)
    for headers in (
        {},
        {"Authorization": "Basic not-a-bearer-scheme"},
        {"Authorization": "Bearer "},
        bearer("rvk_not-a-real-one"),
        bearer(token + "x"),
    ):
        response = await client.get("/api/v1/whoami", headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


async def test_a_revoked_token_stops_working(
    client: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    user_id = await create_admin(db_engine)
    token = await issue(db_engine, user_id)
    before = await client.get("/api/v1/whoami", headers=bearer(token))
    assert before.status_code == 200
    (stored,) = await load_tokens(db_engine)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        user = await session.get(AppUser, user_id)
        assert user is not None
        assert await revoke_api_token(session, user, stored.id, clock.now)
        assert not await revoke_api_token(session, user, stored.id, clock.now)
        assert not await revoke_api_token(session, user, stored.id + 99, clock.now)
    after = await client.get("/api/v1/whoami", headers=bearer(token))
    assert after.status_code == 401


async def test_a_disabled_user_cannot_use_a_token(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    user_id = await create_admin(db_engine)
    token = await issue(db_engine, user_id)
    async with async_sessionmaker(db_engine)() as session, session.begin():
        user = await session.get(AppUser, user_id)
        assert user is not None
        user.is_active = False
    response = await client.get("/api/v1/whoami", headers=bearer(token))
    assert response.status_code == 401


async def test_requests_over_the_limit_get_429_with_a_retry_time(
    client: httpx.AsyncClient, db_engine: AsyncEngine, web_app: FastAPI
) -> None:
    ticks = [1000.0]
    web_app.state.api_limiter = SlidingWindowLimiter(3, 60.0, clock=lambda: ticks[0])
    user_id = await create_admin(db_engine)
    token = await issue(db_engine, user_id)
    for _ in range(3):
        ok = await client.get("/api/v1/whoami", headers=bearer(token))
        assert ok.status_code == 200
    limited = await client.get("/api/v1/whoami", headers=bearer(token))
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "61"
    ticks[0] += 61
    again = await client.get("/api/v1/whoami", headers=bearer(token))
    assert again.status_code == 200


async def test_the_default_limit_is_120_per_minute(web_app: FastAPI) -> None:
    limiter: SlidingWindowLimiter = web_app.state.api_limiter
    results = [limiter.check("one-token") for _ in range(121)]
    assert results[:120] == [None] * 120
    assert results[120] is not None
