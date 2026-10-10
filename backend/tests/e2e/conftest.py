"""End-to-end tests run against the whole development stack (docker compose up -d --wait)."""

import os
import socket
from urllib.parse import urlsplit

import pytest

from tests.support.environment import load_test_environment


@pytest.fixture(scope="session")
def api_url() -> str:
    """Where the api container is reachable from this machine."""
    env = load_test_environment()
    url = os.environ.get("QFE_E2E_API_URL") or f"http://127.0.0.1:{env.get('QFE_PORT_API', '8000')}"
    parts = urlsplit(url)
    try:
        socket.create_connection(
            (parts.hostname or "127.0.0.1", parts.port or 80), timeout=3
        ).close()
    except OSError:
        pytest.fail(
            f"The api is not reachable at {url}. Start the stack with: docker compose up -d --wait",
            pytrace=False,
        )
    return url
