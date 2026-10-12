"""Fixtures for tests that need a real PostgreSQL (the test service from the Compose test profile).

Every test that asks for ``migrated_database`` gets its own database, cloned from the empty
``qfe_template`` that the test service prepares, so tests cannot affect each other.
"""

import asyncio
import os
import socket
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from qfe.adapters.postgres.database import Database as PostgresDatabase
from tests.support.environment import BACKEND_DIR, load_test_environment

START_HINT = (
    "The test PostgreSQL is not reachable. Start the test services with: "
    "docker compose --profile test up -d --wait "
    "postgres-test rabbitmq-test valkey-test storage-test"
)


@dataclass(frozen=True)
class Server:
    host: str
    port: int
    superuser_password: str
    app_password: str
    migrator_password: str

    def url(self, user: str, password: str, database: str) -> str:
        return f"postgresql+asyncpg://{user}:{password}@{self.host}:{self.port}/{database}"


@pytest.fixture(scope="session")
def server() -> Server:
    env = load_test_environment()
    parts = urlsplit(env["QFE_DATABASE_URL"])
    host, port = parts.hostname or "localhost", parts.port or 5432
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError:
        pytest.fail(START_HINT)
    return Server(
        host=host,
        port=port,
        superuser_password=env["QFE_POSTGRES_SUPERUSER_PASSWORD"],
        app_password=env["QFE_APP_DB_PASSWORD"],
        migrator_password=env["QFE_MIGRATOR_DB_PASSWORD"],
    )


@dataclass(frozen=True)
class Database:
    name: str
    server: Server

    @property
    def migrator_url(self) -> str:
        return self.server.url("qfe_migrator", self.server.migrator_password, self.name)

    @property
    def app_url(self) -> str:
        return self.server.url("qfe_app", self.server.app_password, self.name)

    def run_alembic(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the real Alembic command line against this database, as the migrate job does."""
        env = {**os.environ, "QFE_MIGRATOR_DATABASE_URL": self.migrator_url}
        return subprocess.run(  # noqa: S603 - fixed command, arguments come from the tests
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


@pytest.fixture
async def empty_database(server: Server) -> AsyncIterator[Database]:
    """A new database with the roles and privileges prepared but no tables."""
    name = f"qfe_t_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(
        server.url("postgres", server.superuser_password, "postgres"),
        isolation_level="AUTOCOMMIT",
    )
    async with admin.connect() as connection:
        await connection.execute(
            text(f'CREATE DATABASE "{name}" TEMPLATE qfe_template OWNER qfe_migrator')
        )
    try:
        yield Database(name=name, server=server)
    finally:
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def _admin_statement(server: Server, statement: str) -> None:
    admin = create_async_engine(
        server.url("postgres", server.superuser_password, "postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def migrated_template(server: Server) -> Iterator[str]:
    """One database with all migrations applied, used as a template so that each test gets its
    own migrated copy in milliseconds instead of running Alembic again."""
    name = f"qfe_t_template_{uuid.uuid4().hex[:12]}"
    asyncio.run(
        _admin_statement(
            server, f'CREATE DATABASE "{name}" TEMPLATE qfe_template OWNER qfe_migrator'
        )
    )
    try:
        result = Database(name=name, server=server).run_alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        asyncio.run(_admin_statement(server, f'ALTER DATABASE "{name}" WITH IS_TEMPLATE true'))
        yield name
    finally:
        asyncio.run(_admin_statement(server, f'ALTER DATABASE "{name}" WITH IS_TEMPLATE false'))
        asyncio.run(_admin_statement(server, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
async def migrated_database(server: Server, migrated_template: str) -> AsyncIterator[Database]:
    name = f"qfe_t_{uuid.uuid4().hex[:12]}"
    await _admin_statement(
        server, f'CREATE DATABASE "{name}" TEMPLATE "{migrated_template}" OWNER qfe_migrator'
    )
    try:
        yield Database(name=name, server=server)
    finally:
        await _admin_statement(server, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
async def app_engine(migrated_database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator_engine(migrated_database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database.migrator_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(migrated_database: Database) -> AsyncIterator[PostgresDatabase]:
    """The adapter's connection pool, connected as ``qfe_app`` to this test's own database. The
    pool is large enough for the concurrency tests (20 parallel operations)."""
    database = PostgresDatabase(migrated_database.app_url, pool_size=5, max_overflow=30)
    yield database
    await database.dispose()
