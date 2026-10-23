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

It also makes synthetic clients with evidence from every source of the product
(app/devdata.py), so each page can be tried from the interface: DEV_SEED_DATA=0
turns that part off. A client is made once, by its name; a client that exists is
left as it is (delete it on the Settings page and restart to make it again). The
files are invented, hold no password or real name, and are never real data.
"""

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import devdata
from app.audit import add_audit_event
from app.auth import SETUP_LOCK_KEY, normalise_username
from app.checks.library import ControlLibraryError, Library, load_library
from app.clients import create_client
from app.crypto import FieldCipher
from app.db import make_engine
from app.dns_service import look_up_dns, store_dns_check
from app.evidence.assurance import Assurance
from app.evidence.errors import EvidenceError
from app.evidence.files import FileStore
from app.evidence.locking import lock_client
from app.evidence.service import EvidenceContext, NewEvidence, add_evidence
from app.importers.registry import build_default_registry
from app.models import AppUser, Client
from app.posture import load_live
from app.security import hash_password, verify_password
from app.settings import Settings
from app.snapshots import store_snapshot
from app.sources import DNS_SOURCE

logger = logging.getLogger(__name__)

ENABLE_VARIABLE = "DEV_SEED"
ACCOUNTS_VARIABLE = "DEV_SEED_ACCOUNTS"
DATA_VARIABLE = "DEV_SEED_DATA"
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
    else:
        logger.info(
            "dev seed: %d created, %d updated, %d unchanged, %d skipped",
            len(result.created),
            len(result.updated),
            len(result.unchanged),
            len(result.skipped),
        )
    if data_enabled(source):
        run_dev_data(settings)


# --- synthetic clients and evidence ---------------------------------------------------


@dataclass(frozen=True)
class Stage:
    """One round of evidence for a client and the report made after it.

    The files are captured `age_days` days (and an hour) ago in the shape of
    `profile`; the report is made as of `report_days` days ago, or not at all.
    """

    age_days: int
    profile: str
    report_days: int | None


@dataclass(frozen=True)
class DemoClient:
    """A synthetic client: its name, its rounds of evidence and what else it has."""

    name: str
    stages: tuple[Stage, ...] = ()
    sources: tuple[str, ...] = devdata.SOURCES
    manual: bool = False


# A client improving over two months, one that stays weak, one whose evidence went
# stale before its only report, and one with nothing yet (the empty states).
DEMO_CLIENTS = (
    DemoClient(
        "Seed Tidy Ltd (synthetic)",
        (
            Stage(60, devdata.GAPS, 60),
            Stage(30, devdata.TIDY, 30),
            Stage(0, devdata.TIDY, 0),
        ),
        manual=True,
    ),
    DemoClient(
        "Seed Gaps Ltd (synthetic)",
        (
            Stage(60, devdata.GAPS, 60),
            Stage(30, devdata.GAPS, 30),
            Stage(0, devdata.GAPS, 0),
        ),
    ),
    DemoClient(
        "Seed Stale Ltd (synthetic)",
        (Stage(75, devdata.TIDY, 0),),
        sources=(
            "entra-registration",
            "device-inventory",
            "backup-export",
            "network-export",
        ),
    ),
    DemoClient("Seed Empty Ltd (synthetic)"),
)
MANUAL_REVIEWER = "Seed Reviewer"
# A manual artefact (a file, a reviewer and a date) and an attestation (a statement
# with no file), each under a source name of its own.
MANUAL_ARTEFACT_SOURCE = "incident-plan"
ATTESTATION_SOURCE = "access-review"
MANUAL_ARTEFACT_TEXT = (
    b"Synthetic incident response plan.\nOwner: the Seed Reviewer.\n"
    b"No real procedure, contact or credential is described here.\n"
)
REPORT_PERIOD_DAYS = 89


@dataclass(frozen=True)
class DemoResult:
    """What one run of the synthetic data did. Names and counts only."""

    created: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    evidence: int = 0
    reports: int = 0


def data_enabled(env: Mapping[str, str]) -> bool:
    """On unless DEV_SEED_DATA is 0 (the accounts are seeded either way)."""
    return env.get(DATA_VARIABLE, "").strip() != "0"


def evidence_context(settings: Settings) -> EvidenceContext:
    return EvidenceContext(
        files=FileStore(settings.evidence_dir),
        cipher=FieldCipher(settings.fernet_key),
        importers=build_default_registry(),
        settings=settings,
    )


async def seed_stage(
    session: AsyncSession,
    ctx: EvidenceContext,
    library: Library,
    client: DemoClient,
    stage: Stage,
    client_id: int,
    now: datetime,
) -> tuple[int, int]:
    """Add the files of one round, then make its report. Returns (items, reports)."""
    captured = now - timedelta(days=stage.age_days, hours=1)
    added = 0
    for seed in devdata.seed_files(stage.profile, captured):
        if seed.source_code in client.sources:
            evidence = NewEvidence(
                source_code=seed.source_code,
                assurance=Assurance.AUTOMATIC_EXPORT,
                captured_at=captured,
                data=seed.data,
            )
            await add_evidence(session, ctx, client_id, evidence, now)
            added += 1
    if DNS_SOURCE in client.sources:
        check = await look_up_dns(
            devdata.SeedResolver(stage.profile),
            [devdata.MAIL_DOMAINS[stage.profile]],
            devdata.SELECTORS,
            (),
            now=captured,
        )
        await store_dns_check(session, ctx, client_id, check, now=now)
        added += 1
    if stage.report_days is None:
        return added, 0
    as_of = now - timedelta(days=stage.report_days)
    await lock_client(session, client_id)
    live = await load_live(session, library, client_id, as_of)
    end = as_of.date()
    await store_snapshot(
        session,
        client_id,
        live.snapshot,
        end - timedelta(days=REPORT_PERIOD_DAYS),
        end,
    )
    return added, 1


async def seed_manual_evidence(
    session: AsyncSession, ctx: EvidenceContext, client_id: int, now: datetime
) -> int:
    """One manual artefact and one attestation, the two other assurance levels."""
    artefact_at = now - timedelta(days=10)
    await add_evidence(
        session,
        ctx,
        client_id,
        NewEvidence(
            source_code=MANUAL_ARTEFACT_SOURCE,
            assurance=Assurance.MANUAL_ARTEFACT,
            captured_at=artefact_at,
            data=MANUAL_ARTEFACT_TEXT,
            reviewer=MANUAL_REVIEWER,
            reviewed_on=artefact_at.date(),
            note="Synthetic manual artefact for the Development site.",
        ),
        now,
    )
    attested_at = now - timedelta(days=5)
    await add_evidence(
        session,
        ctx,
        client_id,
        NewEvidence(
            source_code=ATTESTATION_SOURCE,
            assurance=Assurance.ATTESTATION,
            captured_at=attested_at,
            reviewer=MANUAL_REVIEWER,
            reviewed_on=attested_at.date(),
            note="Synthetic attestation: access was reviewed. No file is kept.",
        ),
        now,
    )
    return 2


async def seed_demo_data(
    session_factory: async_sessionmaker[AsyncSession],
    ctx: EvidenceContext,
    library: Library,
    now: datetime,
) -> DemoResult:
    """Make the synthetic clients that do not exist yet, one transaction each.

    A client is found by its name; one that exists is left as it is, so a second run
    changes nothing. A failure rolls back the client it happened in only.
    """
    created: list[str] = []
    unchanged: list[str] = []
    evidence = 0
    reports = 0
    for client in DEMO_CLIENTS:
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETUP_LOCK_KEY}
            )
            found = await session.execute(
                select(Client.id).where(Client.name == client.name).limit(1)
            )
            if found.first() is not None:
                unchanged.append(client.name)
                continue
            row = await create_client(session, ctx.cipher, client.name)
            for stage in client.stages:
                items, made = await seed_stage(
                    session, ctx, library, client, stage, row.id, now
                )
                evidence += items
                reports += made
            if client.manual:
                evidence += await seed_manual_evidence(session, ctx, row.id, now)
            created.append(client.name)
    return DemoResult(tuple(created), tuple(unchanged), evidence, reports)


async def _run_data(settings: Settings, now: datetime) -> DemoResult:
    engine = make_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        return await seed_demo_data(
            factory, evidence_context(settings), load_library(), now
        )
    finally:
        await engine.dispose()


def run_dev_data(settings: Settings, now: datetime | None = None) -> None:
    """Make the synthetic clients; never stop the web role (the type is logged)."""
    moment = now or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    try:
        result = asyncio.run(_run_data(settings, moment))
    except (SQLAlchemyError, OSError, EvidenceError, ControlLibraryError) as error:
        logger.error("dev seed: data failed, %s", type(error).__name__)
        return
    logger.info(
        "dev seed: data, %d clients created, %d unchanged, %d evidence items, "
        "%d reports",
        len(result.created),
        len(result.unchanged),
        result.evidence,
        result.reports,
    )
