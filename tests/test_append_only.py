"""audit_event and evidence_log reject UPDATE, DELETE and TRUNCATE in the database.

Every check is plain SQL against PostgreSQL, so it holds for any client of the
database, not only for this application.
"""

import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.audit import add_audit_event
from app.models import AuditEvent

REJECTED = "append-only"
TABLES = ["audit_event", "evidence_log"]
UPDATES = {
    "audit_event": "UPDATE audit_event SET action = 'test.changed' WHERE id = :id",
    "evidence_log": "UPDATE evidence_log SET event_type = 'changed' WHERE id = :id",
}


async def insert_row(engine: AsyncEngine, table: str) -> int:
    """Insert one synthetic row; inserting is allowed."""
    statement = "INSERT INTO audit_event (action) VALUES ('test.append') RETURNING id"
    params: dict[str, Any] = {}
    if table == "evidence_log":
        statement = (
            "INSERT INTO evidence_log (event_type, previous_hash, record_hash) "
            "VALUES ('test', repeat('0', 64), :record_hash) RETURNING id"
        )
        params["record_hash"] = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    async with engine.begin() as connection:
        result = await connection.execute(text(statement), params)
        return int(result.scalar_one())


async def count_rows(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(text(f"SELECT count(*) FROM {table}"))
        return int(result.scalar_one())


@pytest.mark.parametrize("table", TABLES)
async def test_an_update_is_rejected_by_the_database(
    db_engine: AsyncEngine, table: str
) -> None:
    row_id = await insert_row(db_engine, table)
    with pytest.raises(DBAPIError, match=REJECTED):
        async with db_engine.begin() as connection:
            await connection.execute(text(UPDATES[table]), {"id": row_id})


@pytest.mark.parametrize("table", TABLES)
async def test_a_delete_is_rejected_by_the_database(
    db_engine: AsyncEngine, table: str
) -> None:
    row_id = await insert_row(db_engine, table)
    before = await count_rows(db_engine, table)
    with pytest.raises(DBAPIError, match=REJECTED):
        async with db_engine.begin() as connection:
            await connection.execute(
                text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id}
            )
    with pytest.raises(DBAPIError, match=REJECTED):
        async with db_engine.begin() as connection:
            await connection.execute(text(f"DELETE FROM {table}"))
    assert await count_rows(db_engine, table) == before


@pytest.mark.parametrize("table", TABLES)
async def test_a_truncate_is_rejected_by_the_database(
    db_engine: AsyncEngine, table: str
) -> None:
    await insert_row(db_engine, table)
    before = await count_rows(db_engine, table)
    with pytest.raises(DBAPIError, match=REJECTED):
        async with db_engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE {table}"))
    assert await count_rows(db_engine, table) == before


@pytest.mark.parametrize("table", TABLES)
async def test_a_failed_change_leaves_the_row_untouched(
    db_engine: AsyncEngine, table: str
) -> None:
    row_id = await insert_row(db_engine, table)
    with pytest.raises(DBAPIError, match=REJECTED):
        async with db_engine.begin() as connection:
            await connection.execute(text(UPDATES[table]), {"id": row_id})
    column = "action" if table == "audit_event" else "event_type"
    async with db_engine.connect() as connection:
        result = await connection.execute(
            text(f"SELECT {column} FROM {table} WHERE id = :id"), {"id": row_id}
        )
        assert result.scalar_one() in ("test.append", "test")


async def test_the_application_cannot_change_an_audit_row_either(
    db_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(db_engine)
    async with factory() as session, session.begin():
        add_audit_event(session, "test.orm", detail={"note": "synthetic"})
    async with factory() as session:
        event = (
            await session.execute(
                text("SELECT id FROM audit_event WHERE action = 'test.orm'")
            )
        ).first()
        assert event is not None
        row = await session.get(AuditEvent, event[0])
        assert row is not None
        row.action = "test.changed"
        with pytest.raises(DBAPIError, match=REJECTED):
            await session.commit()


async def test_other_tables_are_not_append_only(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO client (name, pseudonym_key_encrypted) "
                "VALUES ('Synthetic Ltd', 'x')"
            )
        )
        await connection.execute(text("UPDATE client SET name = 'Renamed Ltd'"))
        await connection.execute(text("DELETE FROM client"))


@pytest.mark.parametrize("table", TABLES)
async def test_each_table_has_its_row_and_truncate_triggers(
    db_engine: AsyncEngine, table: str
) -> None:
    async with db_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relname = :table AND NOT t.tgisinternal ORDER BY t.tgname"
            ),
            {"table": table},
        )
        names = list(result.scalars())
    assert names == [f"{table}_append_only", f"{table}_no_truncate"]
