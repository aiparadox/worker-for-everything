"""Integration tests need the Compose test services; fail loudly when they are not running."""

import pytest

from tests.support.services import require_test_services


@pytest.fixture(scope="session", autouse=True)
def test_services() -> dict[str, str]:
    return require_test_services()
