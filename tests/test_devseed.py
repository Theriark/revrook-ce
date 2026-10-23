"""The Development test accounts (app/devseed.py): synthetic names and passwords."""

import logging
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import cli, devseed
from app.models import AppUser
from app.settings import Settings
from helpers import audit_baseline, audit_since, login

ONE = "itmanager.synthetic@example.test"
TWO = "info.synthetic@example.test"
ACCOUNTS = f"{ONE},{TWO}"
PASSWORD_ONE = "Seed-Alpha.0123456789"
PASSWORD_TWO = "Seed-Bravo+9876543210"
NEW_PASSWORD_ONE = "Seed-Charlie.5555555555"
DEV_URL = "https://ce-dev-revrook.theriark.dev"


def seed_env(**extra: str) -> dict[str, str]:
    return {
        "DEV_SEED": "1",
        "DEV_SEED_ACCOUNTS": ACCOUNTS,
        "DEV_SEED_PASSWORD_ITMANAGER_SYNTHETIC": PASSWORD_ONE,
        "DEV_SEED_PASSWORD_INFO_SYNTHETIC": PASSWORD_TWO,
        **extra,
    }


async def run_seed(engine: AsyncEngine, env: dict[str, str]) -> devseed.SeedResult:
    async with async_sessionmaker(engine)() as session, session.begin():
        return await devseed.seed_accounts(session, env)


async def load_users(engine: AsyncEngine) -> dict[str, AppUser]:
    async with async_sessionmaker(engine)() as session:
        users = (await session.execute(select(AppUser))).scalars()
        return {user.username: user for user in users}


def test_the_seed_is_off_unless_dev_seed_is_one() -> None:
    assert devseed.seed_enabled({"DEV_SEED": "1"})
    assert devseed.seed_enabled({"DEV_SEED": " 1 "})
    for value in ("", "0", "true", "yes", "11"):
        assert not devseed.seed_enabled({"DEV_SEED": value})
    assert not devseed.seed_enabled({})


@pytest.mark.parametrize(
    "base_url",
    [
        DEV_URL,
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
    ],
)
def test_development_and_local_addresses_may_be_seeded(base_url: str) -> None:
    assert devseed.environment_problem(base_url) is None


@pytest.mark.parametrize(
    "base_url",
    [
        "https://ce-stg-revrook.theriark.dev",
        "https://revrook.example.test",
        "https://ce-dev-revrook.theriark.dev.example.test",
        "https://evil-ce-dev-revrook.theriark.dev",
        "https://example.test/ce-dev-revrook.theriark.dev",
        "",
    ],
)
def test_stage_production_and_look_alike_addresses_are_refused(
    base_url: str,
) -> None:
    assert devseed.environment_problem(base_url) is not None


def test_the_password_variable_follows_the_part_before_the_at_sign() -> None:
    assert devseed.password_variable("itmanager@example.test") == (
        "DEV_SEED_PASSWORD_ITMANAGER"
    )
    assert devseed.password_variable("it.manager-2@example.test") == (
        "DEV_SEED_PASSWORD_IT_MANAGER_2"
    )


def test_the_account_list_is_trimmed_lowered_and_limited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    names = [
        f" {ONE.upper()} ",
        "",
        TWO,
        "bad name",
        "x@",
        "info.synthetic@other.test",
        *[f"user{i}" for i in range(20)],
    ]
    env = {"DEV_SEED_ACCOUNTS": ",".join(names)}
    accounts = devseed.configured_accounts(env)
    assert accounts[:2] == [ONE, TWO]
    # "info.synthetic@other.test" shares a password variable with TWO.
    assert "info.synthetic@other.test" not in accounts
    assert "bad name" not in accounts
    assert len(accounts) == devseed.MAX_ACCOUNTS
    assert "bad name left out" in caplog.text


async def test_the_seed_creates_ordinary_accounts_that_can_sign_in(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    baseline = await audit_baseline(db_engine)
    result = await run_seed(db_engine, seed_env())
    assert result.created == (ONE, TWO)
    users = await load_users(db_engine)
    assert set(users) == {ONE, TWO}
    for user, password in ((users[ONE], PASSWORD_ONE), (users[TWO], PASSWORD_TWO)):
        assert user.is_admin  # CE has one role
        assert user.is_active
        assert user.password_hash.startswith("$argon2id$")
        assert password not in user.password_hash
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["user.created", "user.created"]
    assert all(event.detail == {"dev_seed": True} for event in events)

    signed_in = await login(client, PASSWORD_ONE, ONE.upper())
    assert signed_in.status_code == 303
    assert signed_in.headers["location"] == "/"
    rejected = await login(client, PASSWORD_TWO, ONE)
    assert rejected.status_code == 401


async def test_seeding_twice_changes_nothing_the_second_time(
    db_engine: AsyncEngine,
) -> None:
    await run_seed(db_engine, seed_env())
    first = await load_users(db_engine)
    baseline = await audit_baseline(db_engine)
    result = await run_seed(db_engine, seed_env())
    assert result.unchanged == (ONE, TWO)
    assert result.created == result.updated == result.skipped == ()
    second = await load_users(db_engine)
    assert {n: u.id for n, u in second.items()} == {n: u.id for n, u in first.items()}
    assert {n: u.password_hash for n, u in second.items()} == {
        n: u.password_hash for n, u in first.items()
    }
    assert await audit_since(db_engine, baseline) == []


async def test_a_new_password_replaces_the_old_one_and_clears_a_lockout(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await run_seed(db_engine, seed_env())
    async with async_sessionmaker(db_engine)() as session, session.begin():
        user = (
            await session.execute(select(AppUser).where(AppUser.username == ONE))
        ).scalar_one()
        user.failed_login_count = 5
        user.locked_until = datetime(2099, 1, 1, tzinfo=UTC)
    baseline = await audit_baseline(db_engine)

    result = await run_seed(
        db_engine, seed_env(DEV_SEED_PASSWORD_ITMANAGER_SYNTHETIC=NEW_PASSWORD_ONE)
    )
    assert result.updated == (ONE,)
    assert result.unchanged == (TWO,)
    user = (await load_users(db_engine))[ONE]
    assert user.failed_login_count == 0
    assert user.locked_until is None
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["user.dev_seed_refreshed"]
    assert events[0].detail == {"dev_seed": True, "password_changed": True}

    assert (await login(client, PASSWORD_ONE, ONE)).status_code == 401
    assert (await login(client, NEW_PASSWORD_ONE, ONE)).status_code == 303


async def test_an_account_without_a_valid_password_is_skipped_and_logged(
    db_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    short = "Short.1"
    env = seed_env(DEV_SEED_PASSWORD_ITMANAGER_SYNTHETIC=short)
    del env["DEV_SEED_PASSWORD_INFO_SYNTHETIC"]
    result = await run_seed(db_engine, env)
    assert result.skipped == (ONE, TWO)
    assert await load_users(db_engine) == {}
    assert "DEV_SEED_PASSWORD_ITMANAGER_SYNTHETIC" in caplog.text
    assert "DEV_SEED_PASSWORD_INFO_SYNTHETIC" in caplog.text
    assert short not in caplog.text


@pytest.mark.parametrize(
    "password", ["has space 123456789", "quote'quote12345", "a" * 65]
)
async def test_a_password_outside_the_allowed_characters_is_refused(
    db_engine: AsyncEngine, password: str
) -> None:
    env = seed_env(DEV_SEED_PASSWORD_ITMANAGER_SYNTHETIC=password)
    result = await run_seed(db_engine, env)
    assert result.skipped == (ONE,)
    assert result.created == (TWO,)


async def test_no_account_is_made_when_none_is_listed(
    db_engine: AsyncEngine,
) -> None:
    result = await run_seed(db_engine, {"DEV_SEED": "1"})
    assert result == devseed.SeedResult()
    assert await load_users(db_engine) == {}


def test_a_disabled_seed_does_nothing(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    development = replace(settings, base_url=DEV_URL)
    devseed.run_dev_seed(development, {"DEV_SEED": "0", "DEV_SEED_ACCOUNTS": ONE})
    assert [r for r in caplog.records if r.name == "app.devseed"] == []


@pytest.mark.parametrize(
    "base_url",
    ["https://ce-stg-revrook.theriark.dev", "https://revrook.example.test"],
)
def test_the_seed_refuses_to_run_outside_development(
    settings: Settings, base_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    elsewhere = replace(
        settings,
        base_url=base_url,
        database_url="postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook",
    )
    devseed.run_dev_seed(elsewhere, seed_env())
    assert "dev seed: refused" in caplog.text
    assert "failed" not in caplog.text
    assert PASSWORD_ONE not in caplog.text


def test_a_database_error_is_logged_and_does_not_stop_start_up(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    unreachable = replace(
        settings,
        base_url=DEV_URL,
        database_url="postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook",
    )
    devseed.run_dev_seed(unreachable, seed_env())
    assert "dev seed: failed" in caplog.text
    assert PASSWORD_ONE not in caplog.text
    assert PASSWORD_TWO not in caplog.text


def test_the_web_role_runs_the_seed_after_the_migration(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "upgrade_to_head", lambda: calls.append("migrate"))
    monkeypatch.setattr(cli, "run_dev_seed", lambda s: calls.append("seed"))
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: calls.append("serve"))
    assert cli._serve_web(settings, 8080) == 0
    assert calls == ["migrate", "seed", "serve"]
