"""Upgrade test (phase 11): a database with data at an earlier revision upgrades.

An installation that was set up with an earlier release keeps its data when the
newer image starts and brings the schema up to date (the web role and the migrate
command run `alembic upgrade head`). This test makes that a fact for every revision
since the first one that holds tables. For each of them it

1. builds an empty scratch database next to the test database and upgrades it to
   that revision;
2. seeds one row in every table the revision has, with plain SQL;
3. upgrades to the newest revision, and checks that no row was lost, that the schema
   equals the models (`alembic check`), that the application reads the old rows, and
   that the new columns and tables behave (a default for the old schedule, a
   reminder table that refuses a second row and goes with its client);
4. checks that the database still refuses to change an append-only or immutable row;
5. downgrades back to the seeded revision and upgrades again without losing a row.

The scratch database is dropped afterwards. It needs the same PostgreSQL server as
the other database tests (`DATABASE_URL`), and a database user that may create a
database, which the service container of CI and the compose database both have.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import make_engine
from app.models import Client, Schedule

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = "revrook_upgrade_check"
# The revisions that hold tables: 0001 is an empty baseline.
SEEDED_REVISIONS = ["0002", "0003", "0004", "0005"]
TABLES = [
    "app_user",
    "api_token",
    "client",
    "evidence_item",
    "evidence_revision",
    "fact",
    "snapshot",
    "control_result",
    "exception_record",
    "report_export",
    "schedule",
    "setting",
    "audit_event",
    "evidence_log",
]
# Only columns that exist since revision 0002, so one script seeds every revision.
SEED = """
INSERT INTO app_user (id, username, password_hash)
VALUES (1, 'upgrade-admin', 'not-a-real-hash');
INSERT INTO api_token (id, user_id, name, token_prefix, token_hash)
VALUES (1, 1, 'upgrade token', 'rvk_upgrade', repeat('a', 64));
INSERT INTO client (id, name, pseudonym_key_encrypted)
VALUES (1, 'Upgrade Client Ltd', 'sealed-key-not-real');
INSERT INTO evidence_item
    (id, client_id, source_code, captured_at, sha256, size_bytes, assurance_level)
VALUES
    (1, 1, 'device-inventory', '2026-09-01 08:00:00+00', repeat('b', 64), 1200,
     'automatic-export');
INSERT INTO evidence_revision (id, item_id, revision_number, sha256, size_bytes)
VALUES (1, 1, 1, repeat('b', 64), 1200);
INSERT INTO fact (id, client_id, evidence_item_id, fact_key, value, captured_at)
VALUES (1, 1, 1, 'devices.total', CAST('{"count": 3}' AS jsonb),
        '2026-09-01 08:00:00+00');
INSERT INTO snapshot
    (id, client_id, period_start, period_end, as_of, ruleset_version,
     importer_versions, inputs)
VALUES
    (1, 1, '2026-07-01', '2026-09-30', '2026-10-01 00:00:00+00', '0.1',
     CAST('{}' AS jsonb), CAST('{}' AS jsonb));
INSERT INTO control_result
    (id, snapshot_id, control_id, status, numerator, denominator)
VALUES (1, 1, 'PC-ACC-02', 'pass', 1, 1);
INSERT INTO exception_record
    (id, client_id, control_id, owner, reason, review_date)
VALUES
    (1, 1, 'PC-ACC-02', 'Office manager', 'Accepted for the upgrade test',
     '2027-01-01');
INSERT INTO report_export
    (id, client_id, snapshot_id, kind, filename, file_sha256, size_bytes,
     storage_key, exported_by_id)
VALUES
    (1, 1, 1, 'qbr', 'qbr.html', repeat('c', 64), 900, 'exports/1/qbr', 1);
INSERT INTO schedule (id, name, kind, cron)
VALUES (1, 'upgrade-nightly', 'retention-purge', '30 3 * * *');
INSERT INTO setting (key, value)
VALUES ('msp_name', CAST('"Upgrade MSP"' AS jsonb));
INSERT INTO audit_event (id, action)
VALUES (1, 'client.created');
INSERT INTO evidence_log (id, client_id, event_type, previous_hash, record_hash)
VALUES (1, 1, 'upload', repeat('0', 64), repeat('d', 64));
"""
REMINDER = "INSERT INTO reminder_sent (item_id, threshold_days) VALUES (1, 7)"
CHANGES = {
    "append-only": "UPDATE audit_event SET action = 'changed' WHERE id = 1",
    "immutable": "UPDATE report_export SET kind = 'insurance' WHERE id = 1",
}
CHANGE_REVISION = "UPDATE evidence_revision SET note = 'edited' WHERE id = 1"


def alembic(url: str, *args: str) -> str:
    """Run an Alembic command against `url` in a subprocess; return its output."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{output}"
    return output


def newest_revision() -> str:
    """The head of the revisions in the repository."""
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


@pytest.fixture
async def scratch_url(database_url: str) -> AsyncIterator[str]:
    """An empty database on the same server as the test database."""
    drop = f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)"
    admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text(drop))
            await connection.execute(text(f"CREATE DATABASE {SCRATCH}"))
        url = make_url(database_url).set(database=SCRATCH)
        yield url.render_as_string(hide_password=False)
    finally:
        async with admin.connect() as connection:
            await connection.execute(text(drop))
        await admin.dispose()


async def seed(url: str) -> None:
    engine = make_engine(url)
    try:
        async with engine.begin() as connection:
            for statement in SEED.split(";"):
                if statement.strip():
                    await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def counts(url: str) -> dict[str, int]:
    """The number of rows of every seeded table."""
    engine = make_engine(url)
    found: dict[str, int] = {}
    try:
        async with engine.connect() as connection:
            for table in TABLES:
                statement = f"SELECT count(*) FROM {table}"
                result = await connection.execute(text(statement))
                found[table] = int(result.scalar_one())
    finally:
        await engine.dispose()
    return found


@pytest.mark.parametrize("seeded", SEEDED_REVISIONS)
async def test_a_database_with_data_upgrades_to_the_newest_revision(
    scratch_url: str, seeded: str
) -> None:
    alembic(scratch_url, "upgrade", seeded)
    assert seeded in alembic(scratch_url, "current")
    await seed(scratch_url)
    before = await counts(scratch_url)
    assert before == dict.fromkeys(TABLES, 1)

    # 3. The upgrade keeps every row and ends on the schema of the models.
    alembic(scratch_url, "upgrade", "head")
    assert newest_revision() in alembic(scratch_url, "current")
    assert "No new upgrade operations detected" in alembic(scratch_url, "check")
    assert await counts(scratch_url) == before

    engine = make_engine(scratch_url)
    try:
        async with async_sessionmaker(engine)() as session:
            client = await session.scalar(select(Client).where(Client.id == 1))
            schedule = await session.scalar(select(Schedule).where(Schedule.id == 1))
        assert client is not None and client.name == "Upgrade Client Ltd"
        assert schedule is not None and schedule.name == "upgrade-nightly"
        assert schedule.config == {}

        # 4. The guards of the database hold for rows written before the upgrade.
        for message, statement in CHANGES.items():
            with pytest.raises(DBAPIError, match=message):
                async with engine.begin() as connection:
                    await connection.execute(text(statement))
        with pytest.raises(DBAPIError, match="immutable"):
            async with engine.begin() as connection:
                await connection.execute(text(CHANGE_REVISION))

        # The table the newest revisions added takes one row per item and threshold.
        async with engine.begin() as connection:
            await connection.execute(text(REMINDER))
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text(REMINDER))
        # The row goes again: from revision 0005 the table survives the downgrade
        # of step 5, and the row step 5 inserts would otherwise be refused.
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM reminder_sent"))
    finally:
        await engine.dispose()

    # 5. Down to the seeded revision and up again, without losing a row.
    alembic(scratch_url, "downgrade", seeded)
    assert seeded in alembic(scratch_url, "current")
    assert await counts(scratch_url) == before
    alembic(scratch_url, "upgrade", "head")
    assert await counts(scratch_url) == before

    # A reminder goes with its client; the schedule of the whole installation stays.
    engine = make_engine(scratch_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(REMINDER))
            await connection.execute(text("DELETE FROM client WHERE id = 1"))
            statement = "SELECT count(*) FROM reminder_sent"
            result = await connection.execute(text(statement))
            assert result.scalar_one() == 0
    finally:
        await engine.dispose()
    after = await counts(scratch_url)
    assert after["client"] == after["evidence_item"] == after["report_export"] == 0
    assert after["schedule"] == after["audit_event"] == after["evidence_log"] == 1
