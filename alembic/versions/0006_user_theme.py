"""The theme a person chose for the interface, kept on their user row.

Adds `app_user.theme`: light, dark or system (the theme the system prefers,
the value every existing user gets). The application validates the value
(app/theme.py); the column is a short string so that a future theme needs no
migration.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "theme",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_user", "theme")
