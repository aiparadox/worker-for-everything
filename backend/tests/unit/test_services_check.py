"""Integration tests fail loudly, with the start command, when test services are not running."""

import socket

import pytest

from tests.support import services
from tests.support.services import START_COMMAND, unreachable_services


def closed_port() -> int:
    """A local port with nothing listening on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def env_with_everything_down() -> dict[str, str]:
    port = closed_port()
    return {
        "QFE_DATABASE_URL": f"postgresql+asyncpg://u:p@127.0.0.1:{port}/db",
        "QFE_RABBITMQ_URL": f"amqp://u:p@127.0.0.1:{port}/",
        "QFE_VALKEY_URL": f"redis://127.0.0.1:{port}/0",
        "QFE_STORAGE_ENDPOINT_URL": f"http://127.0.0.1:{port}",
    }


def test_every_service_that_is_down_is_named() -> None:
    assert set(unreachable_services(env_with_everything_down())) == {
        "postgres-test",
        "rabbitmq-test",
        "valkey-test",
        "storage-test",
    }


def test_a_missing_service_fails_the_run_with_the_start_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "load_test_environment", env_with_everything_down)
    with pytest.raises(pytest.fail.Exception) as failure:
        services.require_test_services()
    message = str(failure.value)
    assert "postgres-test" in message
    assert START_COMMAND in message


def test_a_missing_env_file_fails_the_run_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing() -> dict[str, str]:
        raise RuntimeError("missing .env.test in the repository root")

    monkeypatch.setattr(services, "load_test_environment", missing)
    with pytest.raises(pytest.fail.Exception, match=r"missing \.env\.test"):
        services.require_test_services()
