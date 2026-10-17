"""Run the Alembic migrations from inside the application."""

from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent


def upgrade_to_head() -> None:
    """Upgrade the database named by DATABASE_URL to the newest revision.

    alembic/env.py holds a PostgreSQL advisory lock while it works, so two
    processes that start together migrate one after the other.
    """
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    # Keep the caller's logging setup (the web process configures its own).
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
