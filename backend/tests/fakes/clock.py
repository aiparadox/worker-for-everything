"""A clock that tests set and advance, and a token generator that is predictable."""

import itertools
from datetime import UTC, datetime, timedelta


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class SequenceIdGenerator:
    """Tokens ``token-1``, ``token-2`` and so on, long enough to look like the real thing."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def new_token(self) -> str:
        return f"token-{next(self._counter):0>40}"
