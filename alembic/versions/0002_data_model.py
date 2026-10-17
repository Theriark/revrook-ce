"""Phase 1 data model, with append-only audit_event and evidence_log.

Creates the sixteen tables of phase 1. UPDATE, DELETE and TRUNCATE on
audit_event and evidence_log are rejected by triggers (restrict_violation).
The table owner or a superuser can switch the triggers off (ALTER TABLE ...
DISABLE TRIGGER).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = ("audit_event", "evidence_log")

REJECT_FUNCTION = """
CREATE FUNCTION revrook_reject_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: UPDATE, DELETE and TRUNCATE are rejected'
        USING ERRCODE = 'restrict_violation';
END;
$$
"""


def _now_column(name: str, *, nullable: bool = False) -> sa.Column[Any]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.text("now()"),
    )


def _empty_json_column(name: str) -> sa.Column[Any]:
    return sa.Column(
        name,
        postgresql.JSONB(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )


def _id_column() -> sa.Column[Any]:
    return sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True)


def upgrade() -> None:
    op.create_table(
        "app_user",
        _id_column(),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        sa.UniqueConstraint("username", name="uq_app_user_username"),
    )

    op.create_table(
        "api_token",
        _id_column(),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _now_column("created_at"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_api_token_token_hash"),
    )
    op.create_index("ix_api_token_user_id", "api_token", ["user_id"])

    op.create_table(
        "audit_event",
        _id_column(),
        _now_column("occurred_at"),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        _empty_json_column("detail"),
    )
    op.create_index("ix_audit_event_occurred_at", "audit_event", ["occurred_at"])

    op.create_table(
        "setting",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        _now_column("updated_at"),
        sa.Column("updated_by_id", sa.BigInteger(), nullable=True),
    )

    op.create_table(
        "client",
        _id_column(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("pseudonym_key_encrypted", sa.Text(), nullable=False),
        _now_column("created_at"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "evidence_item",
        _id_column(),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_code", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        _now_column("imported_at"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("importer_version", sa.String(32), nullable=True),
        sa.Column("ruleset_version", sa.String(32), nullable=True),
        sa.Column(
            "uploader_id",
            sa.BigInteger(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assurance_level", sa.String(24), nullable=False),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="current",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "assurance_level IN ('automatic-export', 'manual-artefact', 'attestation')",
            name="ck_evidence_item_assurance_level",
        ),
    )
    op.create_index("ix_evidence_item_client_id", "evidence_item", ["client_id"])

    op.create_table(
        "evidence_revision",
        _id_column(),
        sa.Column(
            "item_id",
            sa.BigInteger(),
            sa.ForeignKey("evidence_item.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_id",
            sa.BigInteger(),
            sa.ForeignKey("evidence_revision.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_by_id",
            sa.BigInteger(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _now_column("created_at"),
        sa.UniqueConstraint(
            "item_id",
            "revision_number",
            name="uq_evidence_revision_item_number",
        ),
    )

    op.create_table(
        "evidence_log",
        _id_column(),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_item_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        _empty_json_column("payload"),
        sa.Column("previous_hash", sa.String(64), nullable=False),
        sa.Column("record_hash", sa.String(64), nullable=False),
        _now_column("created_at"),
        sa.UniqueConstraint("record_hash", name="uq_evidence_log_record_hash"),
    )
    op.create_index("ix_evidence_log_client_id", "evidence_log", ["client_id", "id"])

    op.create_table(
        "import_profile",
        _id_column(),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("source_code", sa.String(32), nullable=False),
        sa.Column("mapping", postgresql.JSONB(), nullable=False),
        _now_column("created_at"),
        _now_column("updated_at"),
    )
    op.create_index("ix_import_profile_client_id", "import_profile", ["client_id"])

    op.create_table(
        "fact",
        _id_column(),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_item_id",
            sa.BigInteger(),
            sa.ForeignKey("evidence_item.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact_key", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        _now_column("created_at"),
    )
    op.create_index("ix_fact_client_key", "fact", ["client_id", "fact_key"])
    op.create_index("ix_fact_evidence_item_id", "fact", ["evidence_item_id"])

    op.create_table(
        "snapshot",
        _id_column(),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ruleset_version", sa.String(32), nullable=False),
        sa.Column("importer_versions", postgresql.JSONB(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        _now_column("created_at"),
    )
    op.create_index("ix_snapshot_client_id", "snapshot", ["client_id"])

    op.create_table(
        "control_result",
        _id_column(),
        sa.Column(
            "snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("snapshot.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("control_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("numerator", sa.Integer(), nullable=True),
        sa.Column("denominator", sa.Integer(), nullable=True),
        _empty_json_column("detail"),
        sa.UniqueConstraint(
            "snapshot_id",
            "control_id",
            name="uq_control_result_snapshot_control",
        ),
    )

    op.create_table(
        "exception_record",
        _id_column(),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("control_id", sa.String(32), nullable=False),
        sa.Column("owner", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("compensating_control", sa.Text(), nullable=True),
        sa.Column("review_date", sa.Date(), nullable=False),
        _now_column("created_at"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_exception_record_client_id", "exception_record", ["client_id"])

    op.create_table(
        "report_export",
        _id_column(),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("snapshot.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column(
            "exported_by_id",
            sa.BigInteger(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _now_column("exported_at"),
    )
    op.create_index("ix_report_export_client_id", "report_export", ["client_id"])

    op.create_table(
        "schedule",
        _id_column(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("cron", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        sa.UniqueConstraint("name", name="uq_schedule_name"),
    )

    op.create_table(
        "worker_heartbeat",
        sa.Column("worker_id", sa.String(64), primary_key=True),
        _now_column("beat_at"),
        _empty_json_column("detail"),
    )

    op.execute(REJECT_FUNCTION)
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION revrook_reject_modification()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate "
            f"BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION revrook_reject_modification()"
        )


def downgrade() -> None:
    # Dropping a table drops its triggers; the function goes last.
    for table in (
        "worker_heartbeat",
        "schedule",
        "report_export",
        "exception_record",
        "control_result",
        "snapshot",
        "fact",
        "import_profile",
        "evidence_log",
        "evidence_revision",
        "evidence_item",
        "client",
        "setting",
        "audit_event",
        "api_token",
        "app_user",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION revrook_reject_modification()")
