"""Alembic environment.

The database URL comes from the migrator settings (QFE_MIGRATOR_DATABASE_URL) and nowhere else:
there is no URL in alembic.ini, so a missing setting stops the run instead of using a default
(docs/specs/FEAT-20261010-1204-alembic-schema.md). The schema to compare against is
``qfe.adapters.postgres.tables.metadata``.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from qfe.adapters.postgres.tables import metadata
from qfe.config import MigrateSettings, load_or_exit

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

# Two migrate runs started together must not overlap: the second waits for this lock.
# It is a session-level advisory lock on the migrator's own direct connection (no pooler).
MIGRATION_LOCK_KEY = 8_254_810_442_117


def _database_url() -> str:
    return load_or_exit(MigrateSettings).migrator_database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Write the SQL to the output instead of running it."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
    connection.commit()  # the lock belongs to the session, so it stays after the commit
    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.commit()
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
        connection.commit()


async def run_async_migrations() -> None:
    engine = create_async_engine(_database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
