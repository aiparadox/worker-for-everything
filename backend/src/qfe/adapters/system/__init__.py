"""The real clock and the real random token generator."""

import secrets
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SecretsIdGenerator:
    """Tokens from the operating system's secure random source (192 bits)."""

    def new_token(self) -> str:
        return secrets.token_urlsafe(24)
