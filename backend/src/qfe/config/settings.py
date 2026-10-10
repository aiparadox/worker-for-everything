"""Settings classes, one per kind of process.

Which process needs which required setting is the table in section 3.2 of
docs/specs/FEAT-20261010-1203-config.md. Tuning values (section 3.5) have defaults in code;
those are development starting values, not tuned.
"""

import re
from typing import Literal, Self

from pydantic import Field, PositiveInt, SecretStr, field_validator, model_validator

from qfe.config.base import QfeSettings, check_secret_url, check_url, url_host
from qfe.domain import RetryPolicy

# --- Required settings, in groups -------------------------------------------------------------


class ServiceSettings(QfeSettings):
    """Name of the process and where its telemetry goes."""

    service_name: str = Field(min_length=1)
    # "off" is an explicit choice that is logged at startup (FEAT-20261010-1205), not a fallback.
    telemetry: Literal["on", "off"]
    otlp_endpoint: str | None = None

    @field_validator("otlp_endpoint", mode="before")
    @classmethod
    def _empty_means_not_set(cls, value: object) -> object:
        # Docker Compose passes an unset variable as an empty string. That means "not set"; it is
        # still required when telemetry is on (checked below), so this hides nothing.
        return None if value == "" else value

    @field_validator("otlp_endpoint")
    @classmethod
    def _otlp_is_url(cls, value: str | None) -> str | None:
        if value is not None:
            check_url(value, ("http", "https"), what="the OTLP endpoint")
        return value

    @model_validator(mode="after")
    def _otlp_required_when_on(self) -> Self:
        if self.telemetry == "on" and not self.otlp_endpoint:
            raise ValueError("QFE_OTLP_ENDPOINT is required when QFE_TELEMETRY is on")
        return self


class DatabaseSettings(QfeSettings):
    """Connection as the ``qfe_app`` role (reads and writes data, cannot change the schema)."""

    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def _db_url(cls, value: SecretStr) -> SecretStr:
        return check_secret_url(value, ("postgresql+asyncpg",), what="the database URL")


class BrokerSettings(QfeSettings):
    rabbitmq_url: SecretStr

    @field_validator("rabbitmq_url")
    @classmethod
    def _broker_url(cls, value: SecretStr) -> SecretStr:
        return check_secret_url(value, ("amqp", "amqps"), what="the RabbitMQ URL")


class ValkeySettings(QfeSettings):
    valkey_url: SecretStr

    @field_validator("valkey_url")
    @classmethod
    def _valkey_url(cls, value: SecretStr) -> SecretStr:
        return check_secret_url(value, ("redis", "rediss"), what="the Valkey URL")


class StorageSettings(QfeSettings):
    """Object storage as seen from inside the Docker network."""

    storage_endpoint_url: str
    storage_access_key: SecretStr
    storage_secret_key: SecretStr
    storage_bucket: str = Field(min_length=3)

    @field_validator("storage_endpoint_url")
    @classmethod
    def _storage_url(cls, value: str) -> str:
        return check_url(value, ("http", "https"), what="the storage endpoint URL")


class PublicStorageSettings(StorageSettings):
    """Adds the address clients use in presigned links (a link signed for a Docker-internal
    host name does not work from outside)."""

    storage_public_url: str

    @field_validator("storage_public_url")
    @classmethod
    def _public_url(cls, value: str) -> str:
        return check_url(value, ("http", "https"), what="the public storage URL")

    @model_validator(mode="after")
    def _public_differs_from_internal(self) -> Self:
        if url_host(self.storage_public_url) == url_host(self.storage_endpoint_url):
            raise ValueError(
                "QFE_STORAGE_PUBLIC_URL must use a different host than QFE_STORAGE_ENDPOINT_URL, "
                "otherwise presigned links only work inside Docker"
            )
        return self


class JwtSettings(QfeSettings):
    jwt_secret: SecretStr
    jwt_issuer: str = Field(min_length=1)
    jwt_audience: str = Field(min_length=1)

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("the JWT secret must be at least 32 characters")
        return value


class CorsSettings(QfeSettings):
    """Browser origins allowed to call the API: an explicit list, never ``*``."""

    cors_allowed_origins: str

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.cors_allowed_origins.split(","))

    @field_validator("cors_allowed_origins")
    @classmethod
    def _origins_valid(cls, value: str) -> str:
        parts = [part.strip() for part in value.split(",")]
        for part in parts:
            check_url(part, ("http", "https"), what="each allowed origin")
            # An origin has no path, query or fragment.
            rest = part.split("://", 1)[1]
            if "/" in rest or "?" in rest or "#" in rest:
                raise ValueError("each allowed origin must be scheme, host and port only")
        return value


_JOB_TYPE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class WorkerPoolSettings(QfeSettings):
    """Which job types this worker serves. ``*`` means every type it has code for (D39)."""

    worker_job_types: str

    @property
    def job_types(self) -> tuple[str, ...] | Literal["*"]:
        if self.worker_job_types.strip() == "*":
            return "*"
        return tuple(part.strip() for part in self.worker_job_types.split(","))

    @field_validator("worker_job_types")
    @classmethod
    def _types_valid(cls, value: str) -> str:
        if value.strip() == "*":
            return value
        parts = [part.strip() for part in value.split(",")]
        if any(not _JOB_TYPE_NAME.match(part) for part in parts):
            raise ValueError("must be * or a comma-separated list of job type names")
        if len(set(parts)) != len(parts):
            raise ValueError("job types must not be listed twice")
        return value


# --- Tuning settings (defaults in code, section 3.5 of the spec) --------------------------------


class TokenTuning(QfeSettings):
    access_token_ttl_seconds: PositiveInt = 15 * 60  # D32
    refresh_reuse_window_seconds: PositiveInt = 20  # D37 says 10 to 30
    login_lifetime_days: PositiveInt = 30  # absolute family lifetime (D40)


class RateLimitTuning(QfeSettings):
    rate_limit_api_key_per_minute: PositiveInt = 600
    rate_limit_organisation_per_minute: PositiveInt = 1200
    rate_limit_auth_attempts_per_window: PositiveInt = 10  # login and signup, per IP
    rate_limit_auth_window_seconds: PositiveInt = 15 * 60
    rate_limit_refresh_per_ip_per_minute: PositiveInt = 60
    rate_limit_refresh_per_user_per_minute: PositiveInt = 30
    active_jobs_cap: PositiveInt = 100


class SubmitTuning(QfeSettings):
    presigned_upload_ttl_seconds: PositiveInt = 15 * 60
    presigned_download_ttl_seconds: PositiveInt = 5 * 60
    max_file_bytes: PositiveInt = 100 * 1024 * 1024
    max_payload_bytes: PositiveInt = 256 * 1024


class RetryDefaults(QfeSettings):
    """The default retry policy for a job type that does not define its own (D52 era plan: 3
    retries after the first run, waiting about 10 seconds, 2 minutes and 10 minutes, jitter about
    20%). A bad value stops the process at startup."""

    default_max_attempts: PositiveInt = 4  # the first run plus the retries
    default_retry_delays_seconds: str = "10,120,600"  # one delay before each retry
    default_retry_jitter: float = 0.2

    @property
    def default_retry_policy(self) -> RetryPolicy:
        delays = tuple(float(part) for part in self.default_retry_delays_seconds.split(","))
        return RetryPolicy(self.default_max_attempts, delays, self.default_retry_jitter)

    @model_validator(mode="after")
    def _default_policy_is_valid(self) -> Self:
        try:
            _ = self.default_retry_policy
        except ValueError as error:
            raise ValueError(
                "QFE_DEFAULT_MAX_ATTEMPTS, QFE_DEFAULT_RETRY_DELAYS_SECONDS and "
                f"QFE_DEFAULT_RETRY_JITTER do not make a valid retry policy: {error}"
            ) from None
        return self


class WorkerTuning(RetryDefaults):
    worker_concurrency: PositiveInt = 1  # D35: safe for heavy work, raised per pool
    lease_seconds: PositiveInt = 60
    heartbeat_interval_seconds: PositiveInt = 20
    message_hand_back_delay_seconds: PositiveInt = 5  # exact meaning is set in the worker spec
    max_result_bytes: PositiveInt = 256 * 1024

    @model_validator(mode="after")
    def _heartbeat_inside_lease(self) -> Self:
        if self.heartbeat_interval_seconds >= self.lease_seconds:
            raise ValueError(
                "QFE_HEARTBEAT_INTERVAL_SECONDS must be shorter than QFE_LEASE_SECONDS"
            )
        return self


class MaintenanceTuning(RetryDefaults):
    sweep_base_wait_seconds: PositiveInt = 5 * 60  # D27, D38
    sweep_max_wait_seconds: PositiveInt = 60 * 60
    sweep_batch_size: PositiveInt = 100
    pending_file_expiry_seconds: PositiveInt = 24 * 60 * 60
    job_retention_days: PositiveInt = 30
    published_outbox_retention_seconds: PositiveInt = 24 * 60 * 60

    @model_validator(mode="after")
    def _sweep_cap_not_below_base(self) -> Self:
        if self.sweep_max_wait_seconds < self.sweep_base_wait_seconds:
            raise ValueError(
                "QFE_SWEEP_MAX_WAIT_SECONDS must not be shorter than QFE_SWEEP_BASE_WAIT_SECONDS"
            )
        return self


# --- One class per kind of process ------------------------------------------------------------


class ApiSettings(
    ServiceSettings,
    DatabaseSettings,
    BrokerSettings,
    ValkeySettings,
    PublicStorageSettings,
    JwtSettings,
    CorsSettings,
    TokenTuning,
    RateLimitTuning,
    SubmitTuning,
    RetryDefaults,
):
    pass


class WorkerSettings(
    ServiceSettings,
    DatabaseSettings,
    BrokerSettings,
    StorageSettings,
    WorkerPoolSettings,
    WorkerTuning,
):
    pass


class RelaySettings(ServiceSettings, DatabaseSettings, BrokerSettings):
    pass


class MaintenanceSettings(ServiceSettings, DatabaseSettings, StorageSettings, MaintenanceTuning):
    pass


class MigrateSettings(QfeSettings):
    """The migrate job connects as ``qfe_migrator``, which can change the schema."""

    migrator_database_url: SecretStr

    @field_validator("migrator_database_url")
    @classmethod
    def _db_url(cls, value: SecretStr) -> SecretStr:
        return check_secret_url(value, ("postgresql+asyncpg",), what="the migrator database URL")
