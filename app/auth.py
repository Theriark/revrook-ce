"""Accounts: first-run administrator, sign-in with lockout and API tokens."""

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.models import ApiToken, AppUser
from app.security import (
    dummy_password_hash,
    hash_api_token,
    hash_password,
    new_api_token,
    password_needs_rehash,
    verify_password,
)

LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=5)
# Serialises first-run setup so two simultaneous requests cannot create two admins.
SETUP_LOCK_KEY = 7_262_002

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class SetupClosedError(Exception):
    """First-run setup was refused because a user already exists."""


@dataclass(frozen=True)
class LoginResult:
    outcome: Literal["ok", "invalid", "locked"]
    user: AppUser | None = None
    retry_after: int = 0


def normalise_username(raw: str) -> str:
    return raw.strip().lower()


def validate_new_credentials(username: str, password: str, confirm: str) -> list[str]:
    """Problems with a proposed administrator account, as readable messages."""
    problems: list[str] = []
    if not USERNAME_PATTERN.match(normalise_username(username)):
        problems.append(
            "The username must be 3 to 64 characters: lower-case letters, "
            "digits, dots, dashes or underscores."
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    elif len(password) > MAX_PASSWORD_LENGTH:
        problems.append(
            f"The password must be at most {MAX_PASSWORD_LENGTH} characters."
        )
    elif password.lower() == normalise_username(username):
        problems.append("The password must not be the same as the username.")
    if password != confirm:
        problems.append("The two passwords do not match.")
    return problems


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(AppUser))
    return result.scalar_one()


async def get_user(session: AsyncSession, user_id: int) -> AppUser | None:
    user = await session.get(AppUser, user_id)
    if user is None or not user.is_active:
        return None
    return user


async def create_first_admin(
    session: AsyncSession, username: str, password: str
) -> AppUser:
    """Create the administrator while no user exists; raise SetupClosedError after.

    The caller has validated the input and commits the transaction.
    """
    password_hash = await asyncio.to_thread(hash_password, password)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETUP_LOCK_KEY}
    )
    if await count_users(session) > 0:
        raise SetupClosedError
    user = AppUser(
        username=normalise_username(username),
        password_hash=password_hash,
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
        detail={"first_run": True},
    )
    return user


def _seconds_left(until: datetime, now: datetime) -> int:
    return max(math.ceil((until - now).total_seconds()), 1)


async def authenticate(
    session: AsyncSession, username: str, password: str, now: datetime
) -> LoginResult:
    """Check a sign-in attempt. Failures change state, so the caller always commits.

    Five failed attempts lock the account for five minutes. While it is locked
    the password is not checked, even if it is right. An unknown username costs
    the same password check as a known one.
    """
    if len(password) > MAX_PASSWORD_LENGTH:
        return LoginResult("invalid")
    user: AppUser | None = None
    # PostgreSQL text cannot hold a NUL byte; a name with one cannot exist, so
    # it is treated as an unknown user instead of being sent to the database.
    if "\x00" not in username:
        result = await session.execute(
            select(AppUser)
            .where(AppUser.username == normalise_username(username)[:64])
            .with_for_update()
        )
        user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        await asyncio.to_thread(verify_password, dummy_password_hash(), password)
        add_audit_event(session, "login.failed", detail={"reason": "unknown_user"})
        return LoginResult("invalid")

    if user.locked_until is not None and user.locked_until <= now:
        user.locked_until = None
        user.failed_login_count = 0
    if user.locked_until is not None:
        add_audit_event(session, "login.blocked", actor_user_id=user.id)
        return LoginResult("locked", retry_after=_seconds_left(user.locked_until, now))

    if not await asyncio.to_thread(verify_password, user.password_hash, password):
        user.failed_login_count += 1
        add_audit_event(
            session,
            "login.failed",
            actor_user_id=user.id,
            detail={"reason": "bad_password", "failures": user.failed_login_count},
        )
        if user.failed_login_count >= LOCKOUT_THRESHOLD:
            user.locked_until = now + LOCKOUT_DURATION
            add_audit_event(session, "account.locked", actor_user_id=user.id)
            return LoginResult(
                "locked", retry_after=_seconds_left(user.locked_until, now)
            )
        return LoginResult("invalid")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if password_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, password)
    add_audit_event(session, "login.succeeded", actor_user_id=user.id)
    return LoginResult("ok", user=user)


async def issue_api_token(session: AsyncSession, user: AppUser, name: str) -> str:
    """Create an API token for the user and return it. It cannot be shown again."""
    new = new_api_token()
    api_token = ApiToken(
        user_id=user.id,
        name=name.strip()[:100] or "token",
        token_prefix=new.prefix,
        token_hash=new.token_hash,
    )
    session.add(api_token)
    await session.flush()
    add_audit_event(
        session,
        "api_token.created",
        actor_user_id=user.id,
        target_type="api_token",
        target_id=api_token.id,
        detail={"prefix": new.prefix},
    )
    return new.token


async def revoke_api_token(
    session: AsyncSession, user: AppUser, token_id: int, now: datetime
) -> bool:
    """Revoke one of the user's tokens. False when there is no such live token."""
    api_token = await session.get(ApiToken, token_id)
    if api_token is None or api_token.user_id != user.id:
        return False
    if api_token.revoked_at is not None:
        return False
    api_token.revoked_at = now
    add_audit_event(
        session,
        "api_token.revoked",
        actor_user_id=user.id,
        target_type="api_token",
        target_id=api_token.id,
    )
    return True


async def user_for_api_token(
    session: AsyncSession, token: str, now: datetime
) -> tuple[AppUser, ApiToken] | None:
    """The user a live API token belongs to, or None. Records the use time."""
    result = await session.execute(
        select(ApiToken, AppUser)
        .join(AppUser, AppUser.id == ApiToken.user_id)
        .where(ApiToken.token_hash == hash_api_token(token))
    )
    row = result.first()
    if row is None:
        return None
    api_token, user = row
    if api_token.revoked_at is not None or not user.is_active:
        return None
    api_token.last_used_at = now
    return user, api_token
