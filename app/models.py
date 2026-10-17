"""Database tables of revrook CE (phase 1).

audit_event and evidence_log are append-only: the database rejects UPDATE,
DELETE and TRUNCATE on them with triggers (see alembic revision 0002). Neither
table has a foreign key, so deleting a client never touches them; they hold
ids, hashes and counts, never personal identifiers.

Every key column is an explicit BigInteger. A type inferred from the int
annotation would be Integer and make `alembic check` report a difference.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from app.clock import utcnow
from app.db import Base

EMPTY_JSON = text("'{}'::jsonb")


def timestamp_column(*, required: bool = True) -> MappedColumn[Any]:
    """A timestamptz column filled with the current time when none is given."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=not required,
        default=utcnow,
        server_default=text("now()"),
    )


def optional_timestamp() -> MappedColumn[Any]:
    """A nullable timestamptz column with no default."""
    return mapped_column(DateTime(timezone=True), nullable=True)


def foreign_key(target: str, ondelete: str) -> MappedColumn[Any]:
    """A BigInteger column referencing target (for example client.id)."""
    return mapped_column(BigInteger, ForeignKey(target, ondelete=ondelete))


def json_column() -> MappedColumn[Any]:
    """A JSONB column that defaults to an empty object."""
    return mapped_column(JSONB, default=dict, server_default=EMPTY_JSON)


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("username", name="uq_app_user_username"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = optional_timestamp()
    last_login_at: Mapped[datetime | None] = optional_timestamp()
    created_at: Mapped[datetime] = timestamp_column()


class ApiToken(Base):
    """A bearer token. Only its SHA-256 hash is stored; the token is shown once."""

    __tablename__ = "api_token"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_api_token_token_hash"),
        Index("ix_api_token_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = foreign_key("app_user.id", "CASCADE")
    name: Mapped[str] = mapped_column(String(100))
    token_prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = timestamp_column()
    last_used_at: Mapped[datetime | None] = optional_timestamp()
    revoked_at: Mapped[datetime | None] = optional_timestamp()


class AuditEvent(Base):
    """Append-only record of who did what. Never holds a secret or an identifier."""

    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_event_occurred_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = timestamp_column()
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = json_column()


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
    )
    updated_by_id: Mapped[int | None] = mapped_column(BigInteger)


class Client(Base):
    """An MSP client.

    pseudonym_key_encrypted is the Fernet-encrypted random 32-byte HMAC key of
    this client (decision I6). Deleting the client deletes the key, which makes
    its pseudonyms irreversible.
    """

    __tablename__ = "client"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    pseudonym_key_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_column()
    archived_at: Mapped[datetime | None] = optional_timestamp()


class EvidenceItem(Base):
    __tablename__ = "evidence_item"
    __table_args__ = (
        CheckConstraint(
            "assurance_level IN ('automatic-export', 'manual-artefact', 'attestation')",
            name="ck_evidence_item_assurance_level",
        ),
        Index("ix_evidence_item_client_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = foreign_key("client.id", "CASCADE")
    source_code: Mapped[str] = mapped_column(String(32))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = timestamp_column()
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    importer_version: Mapped[str | None] = mapped_column(String(32))
    ruleset_version: Mapped[str | None] = mapped_column(String(32))
    uploader_id: Mapped[int | None] = foreign_key("app_user.id", "SET NULL")
    assurance_level: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(
        String(24), default="current", server_default="current"
    )
    expires_at: Mapped[datetime | None] = optional_timestamp()


class EvidenceRevision(Base):
    """An immutable revision of an evidence item; a correction is a new revision.

    A database trigger (alembic revision 0003) rejects any change except the
    stored file reference and its retention date, so a purge can drop a raw
    file but nothing can rewrite what was recorded.
    """

    __tablename__ = "evidence_revision"
    __table_args__ = (
        UniqueConstraint(
            "item_id", "revision_number", name="uq_evidence_revision_item_number"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = foreign_key("evidence_item.id", "CASCADE")
    revision_number: Mapped[int] = mapped_column(Integer)
    supersedes_id: Mapped[int | None] = foreign_key("evidence_revision.id", "SET NULL")
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(100))
    reviewed_on: Mapped[date | None] = mapped_column(Date)
    raw_expires_at: Mapped[datetime | None] = optional_timestamp()
    created_by_id: Mapped[int | None] = foreign_key("app_user.id", "SET NULL")
    created_at: Mapped[datetime] = timestamp_column()


class EvidenceLog(Base):
    """Append-only evidence log with one hash chain per client.

    Each record stores the hash of the previous record of the same client; the
    chain is written and verified by app.evidence.chain (phase 2). A record
    without a client is not part of any chain.
    """

    __tablename__ = "evidence_log"
    __table_args__ = (
        UniqueConstraint("record_hash", name="uq_evidence_log_record_hash"),
        Index("ix_evidence_log_client_id", "client_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int | None] = mapped_column(BigInteger)
    evidence_item_id: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = json_column()
    previous_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = timestamp_column()


class ImportProfile(Base):
    __tablename__ = "import_profile"
    __table_args__ = (Index("ix_import_profile_client_id", "client_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int | None] = foreign_key("client.id", "CASCADE")
    name: Mapped[str] = mapped_column(String(100))
    source_code: Mapped[str] = mapped_column(String(32))
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
    )


class Fact(Base):
    """A normalised count or flag taken from one evidence item."""

    __tablename__ = "fact"
    __table_args__ = (
        Index("ix_fact_client_key", "client_id", "fact_key"),
        Index("ix_fact_evidence_item_id", "evidence_item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = foreign_key("client.id", "CASCADE")
    evidence_item_id: Mapped[int] = foreign_key("evidence_item.id", "CASCADE")
    fact_key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamp_column()


class Snapshot(Base):
    __tablename__ = "snapshot"
    __table_args__ = (Index("ix_snapshot_client_id", "client_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = foreign_key("client.id", "CASCADE")
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ruleset_version: Mapped[str] = mapped_column(String(32))
    importer_versions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = timestamp_column()


class ControlResult(Base):
    __tablename__ = "control_result"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "control_id", name="uq_control_result_snapshot_control"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_id: Mapped[int] = foreign_key("snapshot.id", "CASCADE")
    control_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    numerator: Mapped[int | None] = mapped_column(Integer)
    denominator: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict[str, Any]] = json_column()


class ExceptionRecord(Base):
    __tablename__ = "exception_record"
    __table_args__ = (Index("ix_exception_record_client_id", "client_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = foreign_key("client.id", "CASCADE")
    control_id: Mapped[str] = mapped_column(String(32))
    owner: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    compensating_control: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = timestamp_column()
    closed_at: Mapped[datetime | None] = optional_timestamp()


class ReportExport(Base):
    """History of an exported file: its hash and where the immutable copy is."""

    __tablename__ = "report_export"
    __table_args__ = (Index("ix_report_export_client_id", "client_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = foreign_key("client.id", "CASCADE")
    snapshot_id: Mapped[int | None] = foreign_key("snapshot.id", "SET NULL")
    kind: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(255))
    exported_by_id: Mapped[int | None] = foreign_key("app_user.id", "SET NULL")
    exported_at: Mapped[datetime] = timestamp_column()


class Schedule(Base):
    __tablename__ = "schedule"
    __table_args__ = (UniqueConstraint("name", name="uq_schedule_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32))
    cron: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    client_id: Mapped[int | None] = foreign_key("client.id", "CASCADE")
    last_run_at: Mapped[datetime | None] = optional_timestamp()
    next_run_at: Mapped[datetime | None] = optional_timestamp()
    created_at: Mapped[datetime] = timestamp_column()


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    beat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()")
    )
    detail: Mapped[dict[str, Any]] = json_column()
