"""Repository ports: the named operations the rest of the system calls to read and write data.

Only the PostgreSQL adapter writes SQL. Expected business outcomes are typed values, not
exceptions and not HTTP codes; a real failure (the database is down) stays an exception. Every
operation on organisation-owned data takes the organisation id and filters on it; anything
compared with "now" uses the database clock, so callers pass durations, not timestamps
(docs/specs/FEAT-20261010-1211-data-access.md).

Interfaces carry plain data only (small frozen dataclasses), never database objects.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol

from qfe.domain import JobEvent, JobStatus

JsonObject = Mapping[str, Any]

# ---------------------------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UserCreated:
    user_id: uuid.UUID
    organisation_id: uuid.UUID


@dataclass(frozen=True)
class EmailTaken:
    pass


@dataclass(frozen=True)
class SlugTaken:
    pass


CreateUserResult = UserCreated | EmailTaken | SlugTaken


@dataclass(frozen=True)
class PasswordIdentity:
    user_id: uuid.UUID
    user_status: str
    secret_hash: str


@dataclass(frozen=True)
class NewRefreshToken:
    id: uuid.UUID
    """Also the token's ``jti`` claim."""
    family_id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime
    family_expires_at: datetime


@dataclass(frozen=True)
class Rotated:
    token: NewRefreshToken


@dataclass(frozen=True)
class AlreadyRefreshed:
    """The presented token was used moments ago (inside the reuse window): nothing is revoked."""


@dataclass(frozen=True)
class ReuseDetected:
    """A used token was shown again after the reuse window: the whole family is revoked."""


@dataclass(frozen=True)
class FamilyExpired:
    pass


@dataclass(frozen=True)
class Revoked:
    pass


@dataclass(frozen=True)
class Expired:
    pass


@dataclass(frozen=True)
class UnknownToken:
    pass


RotateResult = (
    Rotated | AlreadyRefreshed | ReuseDetected | FamilyExpired | Revoked | Expired | UnknownToken
)


@dataclass(frozen=True)
class Membership:
    role: str
    user_status: str
    organisation_status: str


@dataclass(frozen=True)
class ApiKeyCreated:
    id: uuid.UUID
    created_at: datetime


@dataclass(frozen=True)
class PrefixTaken:
    pass


CreateApiKeyResult = ApiKeyCreated | PrefixTaken


@dataclass(frozen=True)
class ApiKeyRecord:
    """What authentication needs about a key. ``expired`` is decided by the database clock."""

    id: uuid.UUID
    organisation_id: uuid.UUID
    key_hash: bytes
    scopes: tuple[str, ...]
    revoked: bool
    expired: bool
    organisation_status: str
    last_used_at: datetime | None


@dataclass(frozen=True)
class ApiKeySummary:
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: tuple[str, ...]
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class AccountRepository(Protocol):
    async def create_user_with_organisation(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str | None,
        organisation_name: str,
        organisation_slug: str,
    ) -> CreateUserResult:
        """User, password identity, organisation and an owner membership, in one transaction."""
        ...

    async def find_password_identity(self, email: str) -> PasswordIdentity | None:
        """Looked up by ``lower(email)``."""
        ...

    async def record_login(self, user_id: uuid.UUID) -> None: ...

    async def start_login_session(
        self,
        *,
        user_id: uuid.UUID,
        token_lifetime: timedelta,
        family_lifetime: timedelta,
        ip: str | None,
        user_agent: str | None,
    ) -> NewRefreshToken:
        """The first refresh token of a new login: a new family, ending at ``family_lifetime``."""
        ...

    async def rotate_refresh_token(
        self,
        *,
        presented_id: uuid.UUID,
        reuse_window: timedelta,
        token_lifetime: timedelta,
        ip: str | None,
        user_agent: str | None,
    ) -> RotateResult: ...

    async def revoke_token_family(self, family_id: uuid.UUID) -> None:
        """Safe to repeat."""
        ...

    async def read_membership(
        self, *, user_id: uuid.UUID, organisation_id: uuid.UUID
    ) -> Membership | None: ...

    async def create_api_key(
        self,
        *,
        organisation_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        name: str,
        key_prefix: str,
        key_hash: bytes,
        scopes: Sequence[str],
        expires_at: datetime | None,
    ) -> CreateApiKeyResult: ...

    async def find_api_key_by_prefix(self, key_prefix: str) -> ApiKeyRecord | None: ...

    async def touch_api_key_last_used(self, key_id: uuid.UUID, min_interval: timedelta) -> None:
        """Writes ``last_used_at`` at most once per ``min_interval`` (decided in SQL, so it holds
        with several API copies)."""
        ...

    async def list_api_keys(
        self, organisation_id: uuid.UUID, limit: int = 100
    ) -> list[ApiKeySummary]:
        """Revoked and expired keys included; never the hash."""
        ...

    async def revoke_api_key(self, *, organisation_id: uuid.UUID, key_id: uuid.UUID) -> bool:
        """``True`` if the key was found for this organisation. Safe to repeat."""
        ...


# ---------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------


class FileKind(StrEnum):
    INPUT = "input"
    RESULT = "result"


@dataclass(frozen=True)
class FileRecord:
    id: uuid.UUID
    organisation_id: uuid.UUID
    kind: str
    storage_key: str
    display_name: str
    content_type: str
    size_bytes: int
    status: str
    created_at: datetime
    expires_at: datetime | None


class FileRepository(Protocol):
    async def create_file(
        self,
        *,
        organisation_id: uuid.UUID,
        kind: FileKind,
        storage_key: str,
        display_name: str,
        content_type: str,
        size_bytes: int,
        expires_in: timedelta | None,
    ) -> uuid.UUID:
        """A ``pending`` row. The storage key is made by the server, never taken from a client."""
        ...

    async def get_file(
        self, *, organisation_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileRecord | None: ...

    async def mark_files_available(
        self, *, organisation_id: uuid.UUID, file_ids: Sequence[uuid.UUID]
    ) -> list[uuid.UUID]:
        """Sets ``available`` and clears ``expires_at`` (an available file no longer expires
        through the pending-upload cleanup). Returns the ids that were updated. Safe to repeat."""
        ...


# ---------------------------------------------------------------------------------------------
# Jobs: the API side
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewJob:
    organisation_id: uuid.UUID
    api_key_id: uuid.UUID | None
    job_type: str
    type_version: str
    payload: JsonObject
    max_attempts: int
    trace_id: str
    """32 lower-case hex characters."""
    input_file_ids: Sequence[uuid.UUID]
    active_jobs_cap: int
    idempotency_key: str | None = None
    request_hash: bytes | None = None
    """Set together with the key: the same key with a different hash is a conflict."""


@dataclass(frozen=True)
class JobRecord:
    id: uuid.UUID
    organisation_id: uuid.UUID
    api_key_id: uuid.UUID | None
    job_type: str
    type_version: str
    status: JobStatus
    payload: JsonObject
    result: JsonObject | None
    result_file_id: uuid.UUID | None
    error: JsonObject | None
    progress: int
    attempts: int
    max_attempts: int
    priority: int
    cancel_requested: bool
    run_at: datetime
    idempotency_key: str | None
    trace_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class AttemptRecord:
    id: uuid.UUID
    job_id: uuid.UUID
    attempt_number: int
    worker_id: str | None
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    error: JsonObject | None
    trace_id: str | None


@dataclass(frozen=True)
class Created:
    job_id: uuid.UUID


@dataclass(frozen=True)
class Existing:
    """The same idempotency key and the same request: the job made the first time."""

    job: JobRecord


@dataclass(frozen=True)
class IdempotencyConflict:
    """The same idempotency key with a different request."""


@dataclass(frozen=True)
class CapExceeded:
    pass


@dataclass(frozen=True)
class FileUnavailable:
    file_id: uuid.UUID
    """Not available, owned by another organisation, or missing."""


SubmitResult = Created | Existing | IdempotencyConflict | CapExceeded | FileUnavailable


class JobRepository(Protocol):
    async def submit_job(self, job: NewJob) -> SubmitResult:
        """The whole submit transaction: lock, idempotency, files, cap, job, links, outbox row."""
        ...

    async def get_job(
        self, *, organisation_id: uuid.UUID, job_id: uuid.UUID
    ) -> JobRecord | None: ...

    async def list_jobs(
        self,
        *,
        organisation_id: uuid.UUID,
        status: JobStatus | None,
        after_id: uuid.UUID | None,
        limit: int,
    ) -> list[JobRecord]:
        """Newest first; ``after_id`` is the id of the last job of the previous page."""
        ...

    async def list_attempts(
        self, *, organisation_id: uuid.UUID, job_id: uuid.UUID
    ) -> list[AttemptRecord] | None:
        """``None`` when the job does not exist for this organisation."""
        ...


# ---------------------------------------------------------------------------------------------
# Jobs: the worker side
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Claimed:
    job_id: uuid.UUID
    lease_token: uuid.UUID
    attempt_number: int
    organisation_id: uuid.UUID
    job_type: str
    type_version: str
    payload: JsonObject
    trace_id: str
    attempts: int
    max_attempts: int


class RefusalReason(StrEnum):
    NOT_FOUND = "not_found"
    NOT_DUE = "not_due"
    NOT_CLAIMABLE = "not_claimable"
    """The job is running, finished or otherwise not waiting; ``status`` says which."""


@dataclass(frozen=True)
class Refused:
    reason: RefusalReason
    status: JobStatus | None = None


ClaimResult = Claimed | Refused


@dataclass(frozen=True)
class Ok:
    pass


@dataclass(frozen=True)
class LeaseLost:
    """The job is no longer running under this lease token: stop, do not write anything else."""


WriteResult = Ok | LeaseLost

RetryOutcome = Literal["retryable_error", "timeout"]
FailOutcome = Literal["permanent_error", "retryable_error", "timeout"]


class JobExecutionRepository(Protocol):
    async def claim_job(
        self, *, job_id: uuid.UUID, worker_id: str, lease: timedelta
    ) -> ClaimResult: ...

    async def heartbeat_job(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        lease: timedelta,
        progress: int | None,
    ) -> WriteResult: ...

    async def finish_job_success(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        result: JsonObject | None,
        result_file_id: uuid.UUID | None,
    ) -> WriteResult: ...

    async def retry_job(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        delay: timedelta,
        error: JsonObject,
        outcome: RetryOutcome,
    ) -> WriteResult:
        """``retrying`` with ``run_at = now() + delay`` plus one new outbox row, one transaction."""
        ...

    async def fail_job(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        error: JsonObject,
        outcome: FailOutcome,
    ) -> WriteResult: ...


# ---------------------------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpiredLeaseJob:
    """What recovery tells its caller about a job whose lease ran out."""

    job_id: uuid.UUID
    job_type: str
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class Recovered:
    job_id: uuid.UUID
    decision: JobEvent
    """``RETRY`` or ``FAIL``."""


class MaintenanceRepository(Protocol):
    async def recover_expired_leases(
        self, *, batch_size: int, delay_for: Callable[[ExpiredLeaseJob], timedelta]
    ) -> list[Recovered]:
        """Jobs whose lease ran out: fail them if no tries are left, else retry them after
        ``delay_for(job)`` with one outbox row. Each job is its own transaction."""
        ...

    async def sweep_waiting_jobs(
        self, *, batch_size: int, base_wait: timedelta, max_wait: timedelta
    ) -> list[uuid.UUID]:
        """Queue a fresh message for jobs that wait with no message on the way."""
        ...

    async def cleanup_published_outbox(self, *, older_than: timedelta, batch_size: int) -> int: ...

    async def cleanup_refresh_tokens(self, *, grace: timedelta, batch_size: int) -> int: ...

    async def cleanup_pending_files(self, *, batch_size: int) -> list[str]:
        """Deletes ``pending`` rows past their expiry; returns their storage keys so the caller
        deletes the objects."""
        ...

    async def purge_finished_jobs(self, *, older_than: timedelta, batch_size: int) -> int:
        """Only jobs in a final state, oldest ids first, in batches."""
        ...
