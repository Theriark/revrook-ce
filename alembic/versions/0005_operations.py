"""Phase 10 operations: the configuration of a schedule and the reminders sent.

Adds `schedule.config`, the JSON a job needs besides its client (the mail domains
of a DNS check), and the table `reminder_sent`, whose primary key (evidence item,
threshold in days) makes "one reminder per threshold crossing" a rule of the
database. Both go with their client: the schedule row and the evidence item are
deleted with it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedule",
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_table(
        "reminder_sent",
        sa.Column(
            "item_id",
            sa.BigInteger(),
            sa.ForeignKey("evidence_item.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("threshold_days", sa.Integer(), primary_key=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("reminder_sent")
    op.drop_column("schedule", "config")
