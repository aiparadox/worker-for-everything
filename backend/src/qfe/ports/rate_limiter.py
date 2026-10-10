"""The rate limiter port: counts requests and says whether one is allowed.

The first implementation keeps counters in Valkey (D42). The port only answers "allowed or not".
What happens when the counter store is down (fail open for some classes, fail closed for others,
D18) is decided in one place above this port, which handles ``RateLimiterUnavailable``; the active
jobs cap is not here because it is counted exactly in Postgres (D29).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class LimitClass(StrEnum):
    API_KEY = "api_key"
    """Requests per API key. Subject: the key id."""
    ORGANISATION = "organisation"
    """Requests per organisation, all keys together. Subject: the organisation id."""
    AUTH_ATTEMPT = "auth_attempt"
    """Login and signup attempts. Subject: the client IP address."""
    REFRESH = "refresh"
    """Refresh and logout, kept apart from login (D40). Subject: an IP address or a user id."""


@dataclass(frozen=True)
class Rate:
    """``limit`` requests in each window of ``window_seconds``."""

    limit: int
    window_seconds: int


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    """Requests left in this window (0 when not allowed)."""
    reset_after_seconds: int
    """Seconds until the current window ends and the count starts again."""
    retry_after_seconds: int
    """0 when allowed; otherwise how long to wait. Becomes the ``Retry-After`` header."""


class RateLimiterUnavailable(Exception):
    """The counter store could not be reached."""


class RateLimiter(Protocol):
    async def check(self, limit_class: LimitClass, subject: str) -> Decision:
        """Count one request for ``subject`` in ``limit_class`` and say whether it is allowed.
        Raises ``RateLimiterUnavailable`` when the counter store is down."""
        ...
