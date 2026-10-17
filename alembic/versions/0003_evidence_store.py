"""Phase 2 evidence store: reviewer, review date and raw-file expiry per revision.

Adds the columns manual evidence and raw retention need, and a trigger that
keeps evidence revisions immutable: after insert only the stored file
reference and its retention date can change (so a purge can drop the file),
and the two foreign keys to users and to the superseded revision can be
cleared by the database itself.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECT_FUNCTION = """
CREATE FUNCTION revrook_protect_evidence_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.item_id IS DISTINCT FROM OLD.item_id
        OR NEW.revision_number IS DISTINCT FROM OLD.revision_number
        OR NEW.sha256 IS DISTINCT FROM OLD.sha256
        OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
        OR NEW.note IS DISTINCT FROM OLD.note
        OR NEW.reviewer IS DISTINCT FROM OLD.reviewer
        OR NEW.reviewed_on IS DISTINCT FROM OLD.reviewed_on
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR (NEW.supersedes_id IS DISTINCT FROM OLD.supersedes_id
            AND NEW.supersedes_id IS NOT NULL)
        OR (NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
            AND NEW.created_by_id IS NOT NULL)
    THEN
        RAISE EXCEPTION 'evidence revisions are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.add_column(
        "evidence_revision",
        sa.Column("reviewer", sa.String(100), nullable=True),
    )
    op.add_column(
        "evidence_revision",
        sa.Column("reviewed_on", sa.Date(), nullable=True),
    )
    op.add_column(
        "evidence_revision",
        sa.Column("raw_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(PROTECT_FUNCTION)
    op.execute(
        "CREATE TRIGGER evidence_revision_immutable "
        "BEFORE UPDATE ON evidence_revision "
        "FOR EACH ROW EXECUTE FUNCTION revrook_protect_evidence_revision()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER evidence_revision_immutable ON evidence_revision")
    op.execute("DROP FUNCTION revrook_protect_evidence_revision()")
    op.drop_column("evidence_revision", "raw_expires_at")
    op.drop_column("evidence_revision", "reviewed_on")
    op.drop_column("evidence_revision", "reviewer")
