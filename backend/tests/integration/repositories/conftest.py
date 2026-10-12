"""Helpers for the repository tests: each test gets its own database (see the postgres conftest)."""

import itertools
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from qfe.adapters.postgres.accounts import PostgresAccountRepository
from qfe.adapters.postgres.database import Database as PostgresDatabase
from qfe.ports.repositories import UserCreated

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
