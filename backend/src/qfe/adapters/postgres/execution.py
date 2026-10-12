"""Jobs as a worker sees them: claim, heartbeat, finish, retry, fail.

Every write after the claim is guarded by the job's status and its lease token, so a worker that
lost its lease can never overwrite a newer attempt. The statuses a guard allows come from the
domain transition table (``source_statuses``), never from a list written here.
"""

import uuid
from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection

from qfe.adapters.postgres.database import Database, seconds
from qfe.domain import JobEvent, JobStatus, next_status, source_statuses
from qfe.ports.repositories import (
    Claimed,
    ClaimResult,
    FailOutcome,
    JsonObject,
    LeaseLost,
    Ok,
    RefusalReason,
    Refused,
    RetryOutcome,
    WriteResult,
)


def status_list(event: JobEvent) -> str:
    """``'queued', 'retrying'``: the statuses from which ``event`` is legal, for a SQL ``IN``."""
    return ", ".join(f"'{status.value}'" for status in sorted(source_statuses(event)))


class PostgresJobExecutionRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def claim_job(
        self, *, job_id: uuid.UUID, worker_id: str, lease: timedelta
    ) -> ClaimResult:
        running = next_status(JobStatus.QUEUED, JobEvent.CLAIM).value
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        f"UPDATE jobs SET status = '{running}', lease_owner = :worker, "
                        "lease_token = gen_random_uuid(), "
                        "lease_expires_at = now() + make_interval(secs => :lease), "
                        "attempts = attempts + 1, sweep_count = 0, "
                        "started_at = coalesce(started_at, now()), updated_at = now() "
                        f"WHERE id = :id AND status IN ({status_list(JobEvent.CLAIM)}) "
                        "AND run_at <= now() "
                        "RETURNING lease_token, attempts, organisation_id, type, type_version, "
                        "payload, trace_id, max_attempts"
                    ),
                    {"id": job_id, "worker": worker_id, "lease": seconds(lease)},
                )
            ).first()
            if row is None:
                return await _why_refused(conn, job_id)
            await conn.execute(
                sa.text(
                    "INSERT INTO job_attempts (job_id, attempt_number, worker_id, started_at, "
                    "trace_id) VALUES (:job_id, :number, :worker, now(), :trace_id)"
                ),
                {
                    "job_id": job_id,
                    "number": row.attempts,
                    "worker": worker_id,
                    "trace_id": row.trace_id,
                },
            )
        return Claimed(
            job_id=job_id,
            lease_token=row.lease_token,
            attempt_number=row.attempts,
            organisation_id=row.organisation_id,
            job_type=row.type,
            type_version=row.type_version,
            payload=row.payload,
            trace_id=row.trace_id,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
        )

    async def heartbeat_job(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        lease: timedelta,
        progress: int | None,
    ) -> WriteResult:
        if progress is not None and not 0 <= progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "UPDATE jobs SET lease_expires_at = now() + make_interval(secs => :lease), "
                        "progress = coalesce(CAST(:progress AS smallint), progress), "
                        "updated_at = now() "
                        "WHERE id = :id AND status = 'running' AND lease_token = :token "
                        "RETURNING id"
                    ),
                    {
                        "id": job_id,
                        "token": lease_token,
                        "lease": seconds(lease),
                        "progress": progress,
                    },
                )
            ).first()
        return LeaseLost() if row is None else Ok()

    async def finish_job_success(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        result: JsonObject | None,
        result_file_id: uuid.UUID | None,
    ) -> WriteResult:
        if result is not None and result_file_id is not None:
            raise ValueError("a job has a result or a result file, not both")
        done = next_status(JobStatus.RUNNING, JobEvent.SUCCEED).value
        statement = sa.text(
            f"UPDATE jobs SET status = '{done}', result = :result, "
            "result_file_id = :result_file_id, progress = 100, finished_at = now(), "
            "lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() "
            f"WHERE id = :id AND status IN ({status_list(JobEvent.SUCCEED)}) "
            "AND lease_token = :token RETURNING attempts"
        ).bindparams(sa.bindparam("result", type_=postgresql.JSONB(none_as_null=True)))
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    statement,
                    {
                        "id": job_id,
                        "token": lease_token,
                        "result": None if result is None else dict(result),
                        "result_file_id": result_file_id,
                    },
                )
            ).first()
            if row is None:
                return LeaseLost()
            await _close_attempt(conn, job_id, row.attempts, "succeeded", None)
        return Ok()

    async def retry_job(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        delay: timedelta,
        error: JsonObject,
        outcome: RetryOutcome,
    ) -> WriteResult:
        waiting = next_status(JobStatus.RUNNING, JobEvent.RETRY).value
        statement = sa.text(
            f"UPDATE jobs SET status = '{waiting}', "
            "run_at = now() + make_interval(secs => :delay), error = :error, "
            "last_enqueued_at = now(), "
            "lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() "
            f"WHERE id = :id AND status IN ({status_list(JobEvent.RETRY)}) "
            "AND lease_token = :token RETURNING attempts, type, trace_id, run_at"
        ).bindparams(sa.bindparam("error", type_=postgresql.JSONB))
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    statement,
                    {
                        "id": job_id,
                        "token": lease_token,
                        "delay": seconds(delay),
                        "error": dict(error),
                    },
                )
            ).first()
            if row is None:
                return LeaseLost()
            await _close_attempt(conn, job_id, row.attempts, outcome, error)
            await insert_outbox_row(
                conn,
                job_id=job_id,
                routing_key=row.type,
                reason="retry",
                trace_id=row.trace_id,
                run_at=row.run_at,
            )
        return Ok()

    async def fail_job(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        error: JsonObject,
        outcome: FailOutcome,
    ) -> WriteResult:
        failed = next_status(JobStatus.RUNNING, JobEvent.FAIL).value
        statement = sa.text(
            f"UPDATE jobs SET status = '{failed}', error = :error, finished_at = now(), "
            "lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now() "
            f"WHERE id = :id AND status IN ({status_list(JobEvent.FAIL)}) "
            "AND lease_token = :token RETURNING attempts"
        ).bindparams(sa.bindparam("error", type_=postgresql.JSONB))
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    statement, {"id": job_id, "token": lease_token, "error": dict(error)}
                )
            ).first()
            if row is None:
                return LeaseLost()
            await _close_attempt(conn, job_id, row.attempts, outcome, error)
        return Ok()


async def _why_refused(conn: AsyncConnection, job_id: uuid.UUID) -> Refused:
    row = (
        await conn.execute(
            sa.text("SELECT status, run_at > now() AS in_future FROM jobs WHERE id = :id"),
            {"id": job_id},
        )
    ).first()
    if row is None:
        return Refused(RefusalReason.NOT_FOUND)
    status = JobStatus(row.status)
    if status in source_statuses(JobEvent.CLAIM) and row.in_future:
        return Refused(RefusalReason.NOT_DUE, status)
    return Refused(RefusalReason.NOT_CLAIMABLE, status)


async def _close_attempt(
    conn: AsyncConnection,
    job_id: uuid.UUID,
    attempt_number: int,
    outcome: str,
    error: JsonObject | None,
) -> None:
    await conn.execute(
        sa.text(
            "UPDATE job_attempts SET finished_at = now(), outcome = :outcome, error = :error "
            "WHERE job_id = :job_id AND attempt_number = :number AND finished_at IS NULL"
        ).bindparams(sa.bindparam("error", type_=postgresql.JSONB(none_as_null=True))),
        {
            "job_id": job_id,
            "number": attempt_number,
            "outcome": outcome,
            "error": None if error is None else dict(error),
        },
    )


async def insert_outbox_row(
    conn: AsyncConnection,
    *,
    job_id: uuid.UUID,
    routing_key: str,
    reason: str,
    trace_id: str,
    run_at: Any = None,
) -> None:
    """One message to publish: the job's type is the routing key, the body carries the job id, not
    the payload. ``run_at`` None means "now"."""
    await conn.execute(
        sa.text(
            "INSERT INTO outbox (job_id, routing_key, reason, headers, body, run_at) "
            "VALUES (:job_id, :routing_key, :reason, :headers, :body, coalesce(:run_at, now()))"
        ).bindparams(
            sa.bindparam("headers", type_=postgresql.JSONB),
            sa.bindparam("body", type_=postgresql.JSONB),
            sa.bindparam("run_at", type_=sa.DateTime(timezone=True)),
        ),
        {
            "job_id": job_id,
            "routing_key": routing_key,
            "reason": reason,
            "headers": {"trace_id": trace_id},
            "body": {"job_id": str(job_id)},
            "run_at": run_at,
        },
    )
