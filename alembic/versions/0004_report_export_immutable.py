"""Phase 8 export history: a report_export row cannot be changed after it is written.

The row says which file was sent: its hash, size, name, kind and the key of the copy
in the evidence store. After insert nothing of that can change. The only changes the
database still allows are the ones it makes itself: the link to the snapshot or to the
user can be cleared when that snapshot or user is deleted (ON DELETE SET NULL).
Deleting a client removes its exports with it (ON DELETE CASCADE), as before.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECT_FUNCTION = """
CREATE FUNCTION revrook_protect_report_export() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.client_id IS DISTINCT FROM OLD.client_id
        OR NEW.kind IS DISTINCT FROM OLD.kind
        OR NEW.filename IS DISTINCT FROM OLD.filename
        OR NEW.file_sha256 IS DISTINCT FROM OLD.file_sha256
        OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
        OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
        OR NEW.exported_at IS DISTINCT FROM OLD.exported_at
        OR (NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id
            AND NEW.snapshot_id IS NOT NULL)
        OR (NEW.exported_by_id IS DISTINCT FROM OLD.exported_by_id
            AND NEW.exported_by_id IS NOT NULL)
    THEN
        RAISE EXCEPTION 'report exports are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.execute(PROTECT_FUNCTION)
    op.execute(
        "CREATE TRIGGER report_export_immutable "
        "BEFORE UPDATE ON report_export "
        "FOR EACH ROW EXECUTE FUNCTION revrook_protect_report_export()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER report_export_immutable ON report_export")
    op.execute("DROP FUNCTION revrook_protect_report_export()")
