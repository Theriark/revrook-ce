"""The table list of phase 1 and the shape of the key columns (no database)."""

from sqlalchemy import BigInteger

from app import models
from app.db import Base

PHASE_1_TABLES = {
    "app_user",
    "api_token",
    "audit_event",
    "setting",
    "client",
    "evidence_item",
    "evidence_revision",
    "evidence_log",
    "import_profile",
    "fact",
    "control_result",
    "snapshot",
    "exception_record",
    "report_export",
    "schedule",
    "worker_heartbeat",
}
# Phase 10 adds the table that makes "one reminder per threshold" a database rule.
PHASE_10_TABLES = {"reminder_sent"}


def test_the_metadata_holds_exactly_the_tables_of_phases_1_and_10() -> None:
    assert models.AppUser.__table__.metadata is Base.metadata
    assert set(Base.metadata.tables) == PHASE_1_TABLES | PHASE_10_TABLES


def test_key_columns_are_bigint_so_alembic_check_stays_clean() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.primary_key and column.name == "id":
                assert isinstance(column.type, BigInteger), table.name
            for foreign_key in column.foreign_keys:
                assert isinstance(column.type, BigInteger), (table.name, column.name)
                assert foreign_key.ondelete in ("CASCADE", "SET NULL")


def test_the_append_only_tables_have_no_foreign_keys() -> None:
    for name in ("audit_event", "evidence_log"):
        table = Base.metadata.tables[name]
        assert not table.foreign_keys, name


def test_the_client_row_has_an_encrypted_key_column_and_no_plain_key() -> None:
    columns = set(Base.metadata.tables["client"].columns.keys())
    assert "pseudonym_key_encrypted" in columns
    assert not {"pseudonym_key", "key", "secret"} & columns
