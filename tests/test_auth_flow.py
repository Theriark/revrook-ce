"""First-run setup, sign-in, lockout and sign-out against PostgreSQL."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth import SetupClosedError, count_users, create_first_admin
from app.models import AppUser
from app.security import SESSION_COOKIE
from helpers import (
    PASSWORD,
    WRONG_PASSWORD,
    FakeClock,
    audit_baseline,
    audit_since,
    create_admin,
    csrf_from,
    get_csrf,
    login,
)


async def load_user(engine: AsyncEngine, user_id: int) -> AppUser:
    async with async_sessionmaker(engine)() as session:
        user = await session.get(AppUser, user_id)
    assert user is not None
    return user


async def user_count(engine: AsyncEngine) -> int:
    async with async_sessionmaker(engine)() as session:
        return await count_users(session)


def setup_form(
    token: str, username: str, password: str, confirm: str
) -> dict[str, str]:
    return {
        "username": username,
        "password": password,
        "confirm_password": confirm,
        "csrf_token": token,
    }


async def test_with_no_user_the_home_and_login_pages_lead_to_setup(
    client: httpx.AsyncClient,
) -> None:
    for path in ("/", "/login"):
        response = await client.get(path)
        assert response.status_code == 303
        assert response.headers["location"] == "/setup"


async def test_one_admin_can_be_created_from_the_first_run_page(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    baseline = await audit_baseline(db_engine)
    token = await get_csrf(client, "/setup")
    response = await client.post(
        "/setup", data=setup_form(token, " Admin ", PASSWORD, PASSWORD)
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert SESSION_COOKIE in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie

    async with async_sessionmaker(db_engine)() as session:
        users = list((await session.execute(select(AppUser))).scalars())
    assert len(users) == 1
    admin = users[0]
    assert admin.username == "admin"
    assert admin.is_admin
    assert admin.password_hash.startswith("$argon2id$")
    assert PASSWORD not in admin.password_hash

    home = await client.get("/")
    assert home.status_code == 200
    assert "Signed in as admin" in home.text
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["user.created"]
    assert events[0].actor_user_id == admin.id
    assert PASSWORD not in str(events[0].detail)


@pytest.mark.parametrize(
    ("username", "password", "confirm", "message"),
    [
        ("ab", PASSWORD, PASSWORD, "username must be 3 to 64"),
        ("Bad Name!", PASSWORD, PASSWORD, "username must be 3 to 64"),
        ("admin", "short", "short", "at least 12 characters"),
        ("admin", PASSWORD, PASSWORD + "x", "do not match"),
        ("administrator", "ADMINISTRATOR", "ADMINISTRATOR", "same as the user"),
        ("admin", "x" * 257, "x" * 257, "at most 256"),
    ],
)
async def test_first_run_rejects_a_bad_form_and_creates_nothing(
    client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    username: str,
    password: str,
    confirm: str,
    message: str,
) -> None:
    token = await get_csrf(client, "/setup")
    response = await client.post(
        "/setup", data=setup_form(token, username, password, confirm)
    )
    assert response.status_code == 422
    assert message in response.text
    assert await user_count(db_engine) == 0


async def test_the_first_run_form_escapes_what_was_typed(
    client: httpx.AsyncClient,
) -> None:
    token = await get_csrf(client, "/setup")
    response = await client.post(
        "/setup",
        data=setup_form(token, '"><script>alert(1)</script>', "short", "short"),
    )
    assert "<script>alert(1)" not in response.text
    assert "&lt;script&gt;" in response.text


async def test_first_run_is_refused_once_a_user_exists(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    token = await get_csrf(client, "/login")
    response = await client.post(
        "/setup", data=setup_form(token, "second", PASSWORD, PASSWORD)
    )
    assert response.status_code == 403
    assert "Setup is closed" in response.json()["detail"]
    assert await user_count(db_engine) == 1
    page = await client.get("/setup")
    assert page.status_code == 303
    assert page.headers["location"] == "/login"


async def test_two_simultaneous_first_runs_create_exactly_one_admin(
    db_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def attempt(name: str) -> str:
        try:
            async with factory() as session, session.begin():
                await create_first_admin(session, name, PASSWORD)
        except SetupClosedError:
            return "refused"
        return "created"

    outcomes = await asyncio.gather(attempt("first-admin"), attempt("second-admin"))
    assert sorted(outcomes) == ["created", "refused"]
    assert await user_count(db_engine) == 1


async def test_a_correct_login_opens_a_session(
    client: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    user_id = await create_admin(db_engine)
    baseline = await audit_baseline(db_engine)
    response = await login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    home = await client.get("/")
    assert home.status_code == 200
    assert "Signed in as admin" in home.text
    user = await load_user(db_engine, user_id)
    assert user.last_login_at == clock.now
    assert user.failed_login_count == 0
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["login.succeeded"]


async def test_the_csrf_token_changes_at_login_and_at_logout(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    anonymous = await get_csrf(client, "/login")
    await login(client, token=anonymous)
    signed_in = await get_csrf(client, "/")
    assert signed_in != anonymous
    out = await client.post("/logout", data={"csrf_token": signed_in})
    assert out.status_code == 303
    assert out.headers["location"] == "/login"
    after = await get_csrf(client, "/login")
    assert after not in (anonymous, signed_in)
    home = await client.get("/")
    assert home.status_code == 303
    assert home.headers["location"] == "/login"


async def test_logout_accepts_the_token_in_a_header_and_is_audited(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    user_id = await create_admin(db_engine)
    await login(client)
    token = await get_csrf(client, "/")
    baseline = await audit_baseline(db_engine)
    response = await client.post("/logout", headers={"X-CSRF-Token": token})
    assert response.status_code == 303
    events = await audit_since(db_engine, baseline)
    assert [(event.action, event.actor_user_id) for event in events] == [
        ("logout", user_id)
    ]


async def test_a_wrong_password_and_an_unknown_user_look_the_same(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    baseline = await audit_baseline(db_engine)
    token = await get_csrf(client, "/login")
    wrong = await login(client, WRONG_PASSWORD, token=token)
    unknown = await login(client, WRONG_PASSWORD, username="nobody", token=token)
    assert wrong.status_code == unknown.status_code == 401
    assert "username or password is not correct" in wrong.text
    assert "username or password is not correct" in unknown.text
    events = await audit_since(db_engine, baseline)
    assert [event.detail["reason"] for event in events] == [
        "bad_password",
        "unknown_user",
    ]
    assert WRONG_PASSWORD not in str([event.detail for event in events])


async def test_the_login_page_escapes_the_typed_username(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    response = await login(client, username="<b onmouseover=x>")
    assert "<b onmouseover" not in response.text
    assert "&lt;b onmouseover=x&gt;" in response.text
    assert csrf_from(response.text)


async def test_five_failed_logins_lock_the_account_for_five_minutes(
    client: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    user_id = await create_admin(db_engine)
    baseline = await audit_baseline(db_engine)
    token = await get_csrf(client, "/login")
    for _ in range(4):
        response = await login(client, WRONG_PASSWORD, token=token)
        assert response.status_code == 401
    fifth = await login(client, WRONG_PASSWORD, token=token)
    assert fifth.status_code == 429
    assert fifth.headers["retry-after"] == "300"
    assert "locked" in fifth.text

    # While locked even the right password is refused.
    clock.advance(299)
    right = await login(client, PASSWORD, token=token)
    assert right.status_code == 429
    assert right.headers["retry-after"] == "1"
    assert (await client.get("/")).status_code == 303

    clock.advance(2)
    unlocked = await login(client, PASSWORD, token=token)
    assert unlocked.status_code == 303
    user = await load_user(db_engine, user_id)
    assert user.failed_login_count == 0
    assert user.locked_until is None

    actions = [event.action for event in await audit_since(db_engine, baseline)]
    assert actions == (
        ["login.failed"] * 5 + ["account.locked", "login.blocked", "login.succeeded"]
    )


async def test_the_lock_expires_and_the_counter_starts_again(
    client: httpx.AsyncClient, db_engine: AsyncEngine, clock: FakeClock
) -> None:
    user_id = await create_admin(db_engine)
    token = await get_csrf(client, "/login")
    for _ in range(5):
        await login(client, WRONG_PASSWORD, token=token)
    clock.advance(301)
    response = await login(client, WRONG_PASSWORD, token=token)
    assert response.status_code == 401
    user = await load_user(db_engine, user_id)
    assert user.failed_login_count == 1
    assert user.locked_until is None


async def test_a_successful_login_resets_the_failure_counter(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    user_id = await create_admin(db_engine)
    token = await get_csrf(client, "/login")
    for _ in range(3):
        await login(client, WRONG_PASSWORD, token=token)
    assert (await load_user(db_engine, user_id)).failed_login_count == 3
    assert (await login(client, PASSWORD, token=token)).status_code == 303
    assert (await load_user(db_engine, user_id)).failed_login_count == 0
    await client.post("/logout", data={"csrf_token": await get_csrf(client, "/")})
    token = await get_csrf(client, "/login")
    for _ in range(4):
        assert (await login(client, WRONG_PASSWORD, token=token)).status_code == 401


async def test_an_over_long_password_is_refused_without_counting(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    user_id = await create_admin(db_engine)
    response = await login(client, "x" * 1000)
    assert response.status_code == 401
    assert (await load_user(db_engine, user_id)).failed_login_count == 0


async def test_a_forged_session_cookie_is_treated_as_anonymous(
    db_engine: AsyncEngine, web_app: FastAPI
) -> None:
    await create_admin(db_engine)
    transport = httpx.ASGITransport(app=web_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Cookie": f"{SESSION_COOKIE}=forged.value.here"},
    ) as forged:
        response = await forged.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


async def test_pages_are_not_cached_and_keep_the_security_headers(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    response = await client.get("/login")
    assert response.headers["cache-control"] == "no-store, no-transform"
    assert "default-src 'self'" in response.headers["content-security-policy"]


async def test_a_nul_byte_in_the_username_is_an_unknown_user_not_a_server_error(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await create_admin(db_engine)
    baseline = await audit_baseline(db_engine)
    response = await login(client, WRONG_PASSWORD, username="adm\x00in")
    assert response.status_code == 401
    assert "username or password is not correct" in response.text
    events = await audit_since(db_engine, baseline)
    assert [event.detail["reason"] for event in events] == ["unknown_user"]
