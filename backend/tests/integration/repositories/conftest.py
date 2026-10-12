"""Helpers for the repository tests: each test gets its own database (see the postgres conftest)."""

import itertools
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from qfe.adapters.postgres.accounts import PostgresAccountRepository
from qfe.adapters.postgres.database import Database as PostgresDatabase
from qfe.adapters.postgres.files import PostgresFileRepository
from qfe.adapters.postgres.jobs import PostgresJobRepository
from qfe.ports.repositories import FileKind, NewJob, UserCreated

# Fixtures defined for the Postgres tests, made available here by importing them.
from tests.integration.postgres.conftest import (  # noqa: F401
    db,
    empty_database,
    migrated_database,
    migrated_template,
    migrator_engine,
    server,
)

_counter = itertools.count(1)


@dataclass(frozen=True)
class Account:
    user_id: uuid.UUID
    organisation_id: uuid.UUID
    email: str


class AccountFactory(Protocol):
    async def __call__(self, name: str | None = None) -> Account: ...


@pytest.fixture
def accounts(db: PostgresDatabase) -> PostgresAccountRepository:  # noqa: F811
    return PostgresAccountRepository(db)


@pytest.fixture
def make_account(accounts: PostgresAccountRepository) -> AccountFactory:
    """Create a user with an organisation; every call makes a different one."""

    async def make(name: str | None = None) -> Account:
        number = next(_counter)
        email = f"user{number}@example.com" if name is None else f"{name}@example.com"
        result = await accounts.create_user_with_organisation(
            email=email,
            password_hash="argon2-hash-placeholder",
            display_name=None,
            organisation_name=f"Organisation {number}",
            organisation_slug=f"org-{number}-{uuid.uuid4().hex[:6]}",
        )
        assert isinstance(result, UserCreated)
        return Account(result.user_id, result.organisation_id, email)

    return make


class AdminSql:
    """Raw access as the migrator role, to set up or inspect rows the repositories do not expose
    (for example moving a job into a given status)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def run(self, sql: str, **params: object) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def scalar(self, sql: str, **params: object) -> Any:
        async with self._engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar_one()

    async def rows(self, sql: str, **params: object) -> list[Any]:
        async with self._engine.connect() as conn:
            return list((await conn.execute(text(sql), params)).all())


@pytest.fixture
def admin(migrator_engine: AsyncEngine) -> AdminSql:  # noqa: F811
    return AdminSql(migrator_engine)


@pytest.fixture
def files(db: PostgresDatabase) -> PostgresFileRepository:  # noqa: F811
    return PostgresFileRepository(db)


@pytest.fixture
def jobs(db: PostgresDatabase) -> PostgresJobRepository:  # noqa: F811
    return PostgresJobRepository(db)


_job_counter = itertools.count(1)


def new_job(account: Account, **overrides: Any) -> NewJob:
    """A valid submit request for ``account``'s organisation; override any field."""
    number = next(_job_counter)
    values: dict[str, Any] = {
        "organisation_id": account.organisation_id,
        "api_key_id": None,
        "job_type": "echo",
        "type_version": "1",
        "payload": {"message": f"job {number}"},
        "max_attempts": 4,
        "trace_id": uuid.uuid4().hex,
        "input_file_ids": [],
        "active_jobs_cap": 100,
    }
    values.update(overrides)
    return NewJob(**values)


class FileFactory(Protocol):
    async def __call__(
        self, account: Account, *, available: bool = True, kind: FileKind = FileKind.INPUT
    ) -> uuid.UUID: ...


@pytest.fixture
def make_file(files: PostgresFileRepository) -> FileFactory:
    async def make(
        account: Account, *, available: bool = True, kind: FileKind = FileKind.INPUT
    ) -> uuid.UUID:
        file_id = await files.create_file(
            organisation_id=account.organisation_id,
            kind=kind,
            storage_key=f"orgs/{account.organisation_id}/{uuid.uuid4().hex}",
            display_name="doc.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            expires_in=timedelta(hours=1),
        )
        if available:
            await files.mark_files_available(
                organisation_id=account.organisation_id, file_ids=[file_id]
            )
        return file_id

    return make
