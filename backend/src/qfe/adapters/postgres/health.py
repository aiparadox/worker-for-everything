"""Readiness check for PostgreSQL."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from qfe.observability.health import ReadinessCheck


def postgres_check(engine: AsyncEngine) -> ReadinessCheck:
    """Postgres is the system of record, so it is the one critical dependency."""

    async def check() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    return ReadinessCheck(name="postgres", check=check, critical=True)
