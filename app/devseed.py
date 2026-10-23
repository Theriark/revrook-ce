"""Development-only test accounts (DEV_SEED=1).

The Development site needs sign-ins for the people and the browser checks that
test it, and the first-run page creates only one administrator. When DEV_SEED=1
the web role creates the accounts named in DEV_SEED_ACCOUNTS (a comma-separated
list of sign-in names) at start-up, once each. The password of each comes from
the environment at run time, from DEV_SEED_PASSWORD_<NAME>, where NAME is the
part of the sign-in name before any "@" in capitals, with every other character
turned into "_" (itmanager@example.test is DEV_SEED_PASSWORD_ITMANAGER). A
password is never in the code, the logs, the audit trail or the documentation,
and this module never prints one.

Community Edition has one role, so every seeded account is an ordinary CE
account (the same administrator role as the first-run one). No role is invented.

The seed refuses to run unless BASE_URL names a Development host or this
machine, so a copy of the settings on Stage or production does nothing.
"""

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import add_audit_event
from app.auth import SETUP_LOCK_KEY, normalise_username
from app.db import make_engine
from app.models import AppUser
from app.security import hash_password, verify_password
from app.settings import Settings

logger = logging.getLogger(__name__)

ENABLE_VARIABLE = "DEV_SEED"
ACCOUNTS_VARIABLE = "DEV_SEED_ACCOUNTS"
PASSWORD_VARIABLE_PREFIX = "DEV_SEED_PASSWORD_"
MAX_ACCOUNTS = 10
# The sign-in name column holds 64 characters; "@" is allowed here because a
# sign-in name may be an address (the sign-in form takes any text).
ACCOUNT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._@+-]{2,63}$")
PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9._+-]{12,64}$")
DEVELOPMENT_HOST = re.compile(r"^ce-dev-[a-z0-9-]+\.theriark\.dev$")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class SeedResult:
    """What one run did, by sign-in name. Names only, never a password."""

    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def seed_enabled(env: Mapping[str, str]) -> bool:
    return env.get(ENABLE_VARIABLE, "").strip() == "1"


def environment_problem(base_url: str) -> str | None:
    """Why this deployment must not be seeded, or None for Development or local."""
    host = (urlparse(base_url).hostname or "").lower()
    if host in LOCAL_HOSTS or DEVELOPMENT_HOST.match(host):
        return None
    return "BASE_URL is not a Development address"


def password_variable(name: str) -> str:
    """The variable that holds the password of a sign-in name."""
    local = name.split("@", 1)[0].upper()
    return PASSWORD_VARIABLE_PREFIX + re.sub(r"[^A-Z0-9]", "_", local)


def configured_accounts(env: Mapping[str, str]) -> list[str]:
    """The valid, distinct sign-in names of DEV_SEED_ACCOUNTS, in order.

    A malformed name, a second name that would share a password variable, and
    names past the limit are left out and logged (the name only).
    """
    accounts: list[str] = []
    variables: set[str] = set()
    for raw in env.get(ACCOUNTS_VARIABLE, "").split(","):
        if not raw.strip():
            continue
        name = normalise_username(raw)
        variable = password_variable(name)
        if (
            not ACCOUNT_PATTERN.match(name)
            or variable in variables
            or len(accounts) >= MAX_ACCOUNTS
        ):
            logger.warning("dev seed: %s left out of %s", name, ACCOUNTS_VARIABLE)
            continue
        variables.add(variable)
        accounts.append(name)
    return accounts


async def seed_accounts(session: AsyncSession, env: Mapping[str, str]) -> SeedResult:
    """Create or refresh the test accounts; the caller commits the transaction.

    An account whose password variable is missing or malformed is skipped. An
    existing account keeps its row; its password is set to the one in the
    environment when it differs, and a lockout is cleared, so a re-seed with a
    newly registered password makes the two agree.
    """
    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    skipped: list[str] = []
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETUP_LOCK_KEY}
    )
    for name in configured_accounts(env):
        variable = password_variable(name)
        password = env.get(variable, "")
        if not PASSWORD_PATTERN.match(password):
            logger.warning(
                "dev seed: %s skipped, %s is missing or not 12 to 64 of "
                "letters, digits and . _ + -",
                name,
                variable,
            )
            skipped.append(name)
            continue
        user = (
            await session.execute(select(AppUser).where(AppUser.username == name))
        ).scalar_one_or_none()
        if user is None:
            user = AppUser(
                username=name,
                password_hash=await asyncio.to_thread(hash_password, password),
                is_admin=True,
            )
            session.add(user)
            await session.flush()
            add_audit_event(
                session,
                "user.created",
                actor_user_id=user.id,
                target_type="app_user",
                target_id=user.id,
                detail={"dev_seed": True},
            )
            created.append(name)
            continue
        matches = await asyncio.to_thread(verify_password, user.password_hash, password)
        if matches and user.is_active and user.locked_until is None:
            unchanged.append(name)
            continue
        if not matches:
            user.password_hash = await asyncio.to_thread(hash_password, password)
        user.is_active = True
        user.failed_login_count = 0
        user.locked_until = None
        add_audit_event(
            session,
            "user.dev_seed_refreshed",
            actor_user_id=user.id,
            target_type="app_user",
            target_id=user.id,
            detail={"dev_seed": True, "password_changed": not matches},
        )
        updated.append(name)
    return SeedResult(
        created=tuple(created),
        updated=tuple(updated),
        unchanged=tuple(unchanged),
        skipped=tuple(skipped),
    )


async def _run(database_url: str, env: Mapping[str, str]) -> SeedResult:
    engine = make_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            return await seed_accounts(session, env)
    finally:
        await engine.dispose()


def run_dev_seed(settings: Settings, env: Mapping[str, str] | None = None) -> None:
    """Seed the Development accounts when DEV_SEED=1; never stop the web role.

    A refusal or a database error is logged (by type, never with the statement,
    which carries a password hash) and start-up goes on.
    """
    source = os.environ if env is None else env
    if not seed_enabled(source):
        return
    problem = environment_problem(settings.base_url)
    if problem is not None:
        logger.error("dev seed: refused, %s", problem)
        return
    try:
        result = asyncio.run(_run(settings.database_url, source))
    except (SQLAlchemyError, OSError) as error:
        logger.error("dev seed: failed, %s", type(error).__name__)
        return
    logger.info(
        "dev seed: %d created, %d updated, %d unchanged, %d skipped",
        len(result.created),
        len(result.updated),
        len(result.unchanged),
        len(result.skipped),
    )
