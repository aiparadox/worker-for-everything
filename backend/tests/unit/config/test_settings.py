"""Startup configuration checks (docs/specs/FEAT-20261010-1203-config.md)."""

import os
from collections.abc import Iterator

import pytest

from qfe.config import (
    EXIT_CODE_BAD_CONFIG,
    ApiSettings,
    MaintenanceSettings,
    MigrateSettings,
    RelaySettings,
    WorkerSettings,
    load_or_exit,
)
from qfe.config.base import QfeSettings

SERVICE = {"QFE_SERVICE_NAME": "test", "QFE_TELEMETRY": "off"}
DATABASE = {"QFE_DATABASE_URL": "postgresql+asyncpg://qfe_app:fake-pw@postgres:5432/qfe"}
BROKER = {"QFE_RABBITMQ_URL": "amqp://guest:fake-pw@rabbitmq:5672/"}
VALKEY = {"QFE_VALKEY_URL": "redis://valkey:6379/0"}
STORAGE = {
    "QFE_STORAGE_ENDPOINT_URL": "http://storage:8333",
    "QFE_STORAGE_ACCESS_KEY": "fake-access-key",
    "QFE_STORAGE_SECRET_KEY": "fake-secret-key",
    "QFE_STORAGE_BUCKET": "qfe-dev",
}
PUBLIC_STORAGE = {**STORAGE, "QFE_STORAGE_PUBLIC_URL": "http://localhost:8333"}
JWT = {
    "QFE_JWT_SECRET": "fake-only-change-me-fake-only-change-me",
    "QFE_JWT_ISSUER": "qfe",
    "QFE_JWT_AUDIENCE": "qfe-api",
}
CORS = {"QFE_CORS_ALLOWED_ORIGINS": "http://localhost:3000"}
WORKER = {"QFE_WORKER_JOB_TYPES": "*"}

VALID: dict[type[QfeSettings], dict[str, str]] = {
    ApiSettings: {**SERVICE, **DATABASE, **BROKER, **VALKEY, **PUBLIC_STORAGE, **JWT, **CORS},
    WorkerSettings: {**SERVICE, **DATABASE, **BROKER, **STORAGE, **WORKER},
    RelaySettings: {**SERVICE, **DATABASE, **BROKER},
    MaintenanceSettings: {**SERVICE, **DATABASE, **STORAGE},
    MigrateSettings: {
        "QFE_MIGRATOR_DATABASE_URL": "postgresql+asyncpg://qfe_migrator:fake-pw@postgres:5432/qfe"
    },
}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("QFE_"):
            monkeypatch.delenv(name)
    yield


def set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def load_failing(capsys: pytest.CaptureFixture[str], settings_class: type[QfeSettings]) -> str:
    with pytest.raises(SystemExit) as exit_info:
        load_or_exit(settings_class)
    assert exit_info.value.code == EXIT_CODE_BAD_CONFIG
    return capsys.readouterr().err


@pytest.mark.parametrize("settings_class", list(VALID))
def test_valid_settings_load(
    monkeypatch: pytest.MonkeyPatch, settings_class: type[QfeSettings]
) -> None:
    set_env(monkeypatch, VALID[settings_class])
    assert load_or_exit(settings_class) is not None


CASES = [(cls, name) for cls, env in VALID.items() for name in env]


@pytest.mark.parametrize(("settings_class", "missing"), CASES)
def test_each_required_variable_is_required(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings_class: type[QfeSettings],
    missing: str,
) -> None:
    env = {k: v for k, v in VALID[settings_class].items() if k != missing}
    set_env(monkeypatch, env)
    message = load_failing(capsys, settings_class)
    assert missing in message
    assert "missing" in message


def test_all_problems_are_reported_at_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    message = load_failing(capsys, ApiSettings)  # nothing set at all
    for name in ("QFE_DATABASE_URL", "QFE_RABBITMQ_URL", "QFE_VALKEY_URL", "QFE_JWT_SECRET"):
        assert name in message


def test_empty_string_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    set_env(monkeypatch, {**VALID[RelaySettings], "QFE_SERVICE_NAME": ""})
    assert "QFE_SERVICE_NAME" in load_failing(capsys, RelaySettings)


def test_secret_values_never_appear_in_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {
        **VALID[ApiSettings],
        "QFE_JWT_SECRET": "shortsecret123",
        "QFE_DATABASE_URL": "mysql://user:hunter2pw@host/db",
    }
    set_env(monkeypatch, env)
    message = load_failing(capsys, ApiSettings)
    assert "QFE_JWT_SECRET" in message
    assert "QFE_DATABASE_URL" in message
    assert "shortsecret123" not in message
    assert "hunter2pw" not in message


def test_secret_values_never_appear_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, VALID[ApiSettings])
    text = repr(load_or_exit(ApiSettings))
    for secret in ("fake-only-change-me", "fake-pw", "fake-secret-key", "fake-access-key"):
        assert secret not in text


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("QFE_DATABASE_URL", "postgresql://u:p@h/db"),  # wrong driver
        ("QFE_RABBITMQ_URL", "http://rabbitmq"),
        ("QFE_VALKEY_URL", "amqp://valkey"),
        ("QFE_STORAGE_ENDPOINT_URL", "storage:8333"),
        ("QFE_STORAGE_BUCKET", "ab"),
        ("QFE_JWT_SECRET", "x" * 31),
        ("QFE_CORS_ALLOWED_ORIGINS", "*"),
        ("QFE_CORS_ALLOWED_ORIGINS", "http://localhost:3000/app"),
        ("QFE_CORS_ALLOWED_ORIGINS", "http://localhost:3000,not-a-url"),
        ("QFE_STORAGE_PUBLIC_URL", "http://storage:8333"),  # same host as the internal URL
        ("QFE_TELEMETRY", "maybe"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    value: str,
) -> None:
    set_env(monkeypatch, {**VALID[ApiSettings], variable: value})
    assert variable in load_failing(capsys, ApiSettings)


def test_otlp_endpoint_required_only_when_telemetry_is_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    set_env(monkeypatch, {**VALID[RelaySettings], "QFE_TELEMETRY": "on"})
    assert "QFE_OTLP_ENDPOINT" in load_failing(capsys, RelaySettings)
    monkeypatch.setenv("QFE_OTLP_ENDPOINT", "http://otel-lgtm:4318")
    assert load_or_exit(RelaySettings).telemetry == "on"


@pytest.mark.parametrize("value", ["", "a,,b", "Bad Name", "a,a", "*,a"])
def test_invalid_worker_job_types(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    set_env(monkeypatch, {**VALID[WorkerSettings], "QFE_WORKER_JOB_TYPES": value})
    assert "QFE_WORKER_JOB_TYPES" in load_failing(capsys, WorkerSettings)


def test_worker_job_types_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {**VALID[WorkerSettings], "QFE_WORKER_JOB_TYPES": "ocr.extract, echo"})
    assert load_or_exit(WorkerSettings).job_types == ("ocr.extract", "echo")
    monkeypatch.setenv("QFE_WORKER_JOB_TYPES", "*")
    assert load_or_exit(WorkerSettings).job_types == "*"


def test_heartbeat_must_be_shorter_than_lease(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    set_env(monkeypatch, {**VALID[WorkerSettings], "QFE_HEARTBEAT_INTERVAL_SECONDS": "60"})
    assert "QFE_HEARTBEAT_INTERVAL_SECONDS" in load_failing(capsys, WorkerSettings)


def test_tuning_defaults_match_the_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, VALID[WorkerSettings])
    worker = load_or_exit(WorkerSettings)
    assert (worker.lease_seconds, worker.heartbeat_interval_seconds) == (60, 20)
    assert worker.worker_concurrency == 1
    set_env(monkeypatch, VALID[MaintenanceSettings])
    maintenance = load_or_exit(MaintenanceSettings)
    assert (maintenance.sweep_base_wait_seconds, maintenance.sweep_max_wait_seconds) == (300, 3600)
    set_env(monkeypatch, VALID[ApiSettings])
    api = load_or_exit(ApiSettings)
    assert api.access_token_ttl_seconds == 900
    assert api.refresh_reuse_window_seconds == 20
    assert api.active_jobs_cap == 100


def test_tuning_values_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {**VALID[WorkerSettings], "QFE_WORKER_CONCURRENCY": "4"})
    assert load_or_exit(WorkerSettings).worker_concurrency == 4


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_tuning_values_must_be_positive_numbers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    set_env(monkeypatch, {**VALID[WorkerSettings], "QFE_WORKER_CONCURRENCY": value})
    assert "QFE_WORKER_CONCURRENCY" in load_failing(capsys, WorkerSettings)


def test_a_process_does_not_need_other_processes_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The relay must start without a JWT secret, storage or Valkey (spec section 3.2).
    set_env(monkeypatch, VALID[RelaySettings])
    assert load_or_exit(RelaySettings) is not None


def test_an_empty_otlp_endpoint_means_not_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Docker Compose passes an unset variable as an empty string.
    set_env(monkeypatch, {**VALID[RelaySettings], "QFE_OTLP_ENDPOINT": ""})
    assert load_or_exit(RelaySettings).otlp_endpoint is None
    monkeypatch.setenv("QFE_TELEMETRY", "on")
    assert "QFE_OTLP_ENDPOINT" in load_failing(capsys, RelaySettings)
