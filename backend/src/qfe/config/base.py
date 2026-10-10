"""Shared base for all settings classes, and the checks that several settings share.

Rules (CLAUDE.md Module 4, docs/specs/FEAT-20261010-1203-config.md):
- every variable starts with ``QFE_``;
- a required setting has no default, so a missing value stops the process at startup;
- validation messages never contain the offending value, because it may be a secret.
"""

from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class QfeSettings(BaseSettings):
    """Base class: reads ``QFE_*`` environment variables only, never a hidden .env file."""

    model_config = SettingsConfigDict(
        env_prefix="QFE_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )


def check_url(value: str, schemes: tuple[str, ...], *, what: str) -> str:
    """Return ``value`` if it is a URL with an allowed scheme and a host, else raise."""
    parts = urlsplit(value)
    if parts.scheme not in schemes or not parts.hostname:
        allowed = ", ".join(schemes)
        raise ValueError(f"{what} must be a URL starting with one of: {allowed}")
    return value


def check_secret_url(value: SecretStr, schemes: tuple[str, ...], *, what: str) -> SecretStr:
    """Same as ``check_url`` for a URL that may carry a password."""
    check_url(value.get_secret_value(), schemes, what=what)
    return value


def url_host(value: str) -> str:
    """Lower-case host name of a URL."""
    return (urlsplit(value).hostname or "").lower()
