"""Alembic environment: async engine on asyncpg.

The URL comes from DATABASE_URL, not from Settings, so migrations run without
SECRET_KEY and FERNET_KEY (the CI migrations job sets only DATABASE_URL).
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base

# Held for the length of a migration so two processes that start together (for
# example two web replicas running `revrook web`) never migrate at once.
MIGRATION_LOCK_KEY = 7_262_003

config = context.config
# app.migrate sets configure_logger to False so running a migration inside the
# web process does not replace its logging setup.
configure_logger = config.attributes.get("configure_logger", True)
if config.config_file_name is not None and configure_logger:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required to run migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        # Transaction-level lock: released at commit or rollback. The current
        # revision is read after it is taken, so the second process sees the
        # result of the first and has nothing left to do.
        connection.execute(text(f"SELECT pg_advisory_xact_lock({MIGRATION_LOCK_KEY})"))
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
