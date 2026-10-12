"""The connection pool of one process, and small helpers shared by the repositories."""

from contextlib import AbstractAsyncContextManager
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


class Database:
    """Owns the async engine of a process. Each repository operation opens its own transaction
    with ``begin()`` and finishes it; no session is shared between calls."""

    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 5,
        pool_timeout_seconds: float = 30,
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout_seconds,
            pool_pre_ping=True,
        )

    def begin(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """A transaction: commits when the block ends normally, rolls back on an exception."""
        return self.engine.begin()

    async def dispose(self) -> None:
        await self.engine.dispose()


def seconds(duration: timedelta) -> float:
    """A duration as seconds, for ``make_interval(secs => :value)`` in SQL."""
    return duration.total_seconds()


def constraint_name(error: IntegrityError) -> str | None:
    """The name of the constraint or unique index a failed statement broke, if the driver says."""
    cause = getattr(error.orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None)
    return name if isinstance(name, str) else None
