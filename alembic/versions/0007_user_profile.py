"""The profile of a person: a display name and a picture, kept on their user row.

Adds to `app_user`: `display_name` (shown in the header menu instead of the login
name when set), `avatar` (the picture as uploaded, PNG, JPEG or WebP, at most
512 KB; the application checks its first bytes) with its media type
`avatar_type`, and `avatar_version`, raised on every change so the address of the
picture changes and no cache serves the old one. Every existing user gets none.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("display_name", sa.String(length=80)))
    op.add_column("app_user", sa.Column("avatar", sa.LargeBinary()))
    op.add_column("app_user", sa.Column("avatar_type", sa.String(length=16)))
    op.add_column(
        "app_user",
        sa.Column(
            "avatar_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_user", "avatar_version")
    op.drop_column("app_user", "avatar_type")
    op.drop_column("app_user", "avatar")
    op.drop_column("app_user", "display_name")
