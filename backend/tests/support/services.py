"""Checking that the Compose test services are running, with one clear failure message.

Integration and end-to-end tests never skip quietly when a service is missing: a skipped test
looks like a pass.
"""

import socket
from urllib.parse import urlsplit

import pytest

from tests.support.environment import load_test_environment

START_COMMAND = (
    "docker compose --profile test up -d --wait "
    "postgres-test rabbitmq-test valkey-test storage-test"
)

# The setting that holds each service's address in the test environment.
SERVICE_URL_SETTINGS = {
    "postgres-test": "QFE_DATABASE_URL",
    "rabbitmq-test": "QFE_RABBITMQ_URL",
    "valkey-test": "QFE_VALKEY_URL",
    "storage-test": "QFE_STORAGE_ENDPOINT_URL",
}


def is_reachable(url: str, *, timeout: float = 3.0) -> bool:
    parts = urlsplit(url)
    try:
        socket.create_connection(
            (parts.hostname or "127.0.0.1", parts.port or 80), timeout=timeout
        ).close()
    except OSError:
        return False
    return True


def unreachable_services(env: dict[str, str]) -> list[str]:
    return [
        service
        for service, setting in SERVICE_URL_SETTINGS.items()
        if not is_reachable(env[setting])
    ]


def require_test_services() -> dict[str, str]:
    """Return the test environment, or fail the test run naming the services that are down."""
    try:
        env = load_test_environment()
    except RuntimeError as error:
        pytest.fail(str(error), pytrace=False)
    down = unreachable_services(env)
    if down:
        pytest.fail(
            f"These test services are not reachable: {', '.join(down)}. "
            f"Start them with: {START_COMMAND}",
            pytrace=False,
        )
    return env
