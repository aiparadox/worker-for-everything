"""Jobs as the API sees them: submit, read, list, and the attempts of a job.

``submit_job`` is the whole submit transaction (docs/ARCHITECTURE.md section 5, step 3). Lock order:
the organisation's advisory lock, then the file rows ``FOR SHARE``, then the inserts. No other
operation takes the advisory lock, so no lock cycle is possible. Storage checks happen before this
is called (D36), so the lock lasts a few milliseconds.
"""

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from qfe.adapters.postgres.database import Database, constraint_name
from qfe.domain import LIVE_STATUSES, JobStatus
from qfe.ports.repositories import (
    AttemptRecord,
    CapExceeded,
    Created,
    Existing,
    FileUnavailable,
    IdempotencyConflict,
    JobRecord,
    NewJob,
    SubmitResult,
)

# Written inline (not as a bound array) so the planner can match the partial index on live jobs.
LIVE_STATUS_SQL = ", ".join(f"'{status.value}'" for status in sorted(LIVE_STATUSES))

JOB_COLUMNS = (
    "id, organisation_id, api_key_id, type, type_version, status, payload, result, result_file_id, "
    "error, progress, attempts, max_attempts, priority, cancel_requested, run_at, "
    "idempotency_key, trace_id, created_at, started_at, finished_at, updated_at"
)
_IDEMPOTENCY_INDEX = "uq_jobs_organisation_id_idempotency_key"


def job_record(row: Any) -> JobRecord:
    return JobRecord(
        id=row.id,
        organisation_id=row.organisation_id,
        api_key_id=row.api_key_id,
        job_type=row.type,
        type_version=row.type_version,
        status=JobStatus(row.status),
        payload=row.payload,
        result=row.result,
        result_file_id=row.result_file_id,
        error=row.error,
        progress=row.progress,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        priority=row.priority,
        cancel_requested=row.cancel_requested,
        run_at=row.run_at,
        idempotency_key=row.idempotency_key,
        trace_id=row.trace_id,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        updated_at=row.updated_at,
    )


class PostgresJobRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def submit_job(self, job: NewJob) -> SubmitResult:
        try:
            async with self._db.begin() as conn:
                return await self._submit(conn, job)
        except IntegrityError as error:
            # Normally impossible, because the lock serialises same-organisation submits. If two
            # requests with one key still collide, return the first one's job.
            if job.idempotency_key is not None and constraint_name(error) == _IDEMPOTENCY_INDEX:
                async with self._db.begin() as conn:
                    earlier = await _existing_for_key(conn, job)
                if earlier is not None:
                    return earlier
            raise

    async def _submit(self, conn: AsyncConnection, job: NewJob) -> SubmitResult:
        await conn.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:organisation_id, 0))"),
            {"organisation_id": str(job.organisation_id)},
        )

        if job.idempotency_key is not None:
            earlier = await _existing_for_key(conn, job)
            if earlier is not None:
                return earlier

        unavailable = await _first_unavailable_file(conn, job)
        if unavailable is not None:
            return FileUnavailable(unavailable)

        live = (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM ("
                    "SELECT 1 FROM jobs WHERE organisation_id = :organisation_id "
                    f"AND status IN ({LIVE_STATUS_SQL}) LIMIT :stop) AS live_jobs"
                ),
                {"organisation_id": job.organisation_id, "stop": job.active_jobs_cap + 1},
            )
        ).scalar_one()
        if live >= job.active_jobs_cap:
            return CapExceeded()

        job_id = (
            await conn.execute(
                sa.text(
                    "INSERT INTO jobs (organisation_id, api_key_id, type, type_version, payload, "
                    "max_attempts, idempotency_key, request_hash, trace_id) "
                    "VALUES (:organisation_id, :api_key_id, :type, :type_version, :payload, "
                    ":max_attempts, :idempotency_key, :request_hash, :trace_id) RETURNING id"
                ).bindparams(sa.bindparam("payload", type_=postgresql.JSONB)),
                {
                    "organisation_id": job.organisation_id,
                    "api_key_id": job.api_key_id,
                    "type": job.job_type,
                    "type_version": job.type_version,
                    "payload": dict(job.payload),
                    "max_attempts": job.max_attempts,
                    "idempotency_key": job.idempotency_key,
                    "request_hash": job.request_hash,
                    "trace_id": job.trace_id,
                },
            )
        ).scalar_one()

        for file_id in dict.fromkeys(job.input_file_ids):
            await conn.execute(
                sa.text("INSERT INTO job_files (job_id, file_id) VALUES (:job_id, :file_id)"),
                {"job_id": job_id, "file_id": file_id},
            )

        await conn.execute(
            sa.text(
                "INSERT INTO outbox (job_id, routing_key, reason, headers, body) "
                "VALUES (:job_id, :routing_key, 'submit', :headers, :body)"
            ).bindparams(
                sa.bindparam("headers", type_=postgresql.JSONB),
                sa.bindparam("body", type_=postgresql.JSONB),
            ),
            {
                "job_id": job_id,
                "routing_key": job.job_type,
                "headers": {"trace_id": job.trace_id},
                "body": {"job_id": str(job_id)},
            },
        )
        return Created(job_id)

    async def get_job(self, *, organisation_id: uuid.UUID, job_id: uuid.UUID) -> JobRecord | None:
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        f"SELECT {JOB_COLUMNS} FROM jobs "
                        "WHERE id = :id AND organisation_id = :organisation_id"
                    ),
                    {"id": job_id, "organisation_id": organisation_id},
                )
            ).first()
        return None if row is None else job_record(row)

    async def list_jobs(
        self,
        *,
        organisation_id: uuid.UUID,
        status: JobStatus | None,
        after_id: uuid.UUID | None,
        limit: int,
    ) -> list[JobRecord]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        conditions = ["organisation_id = :organisation_id"]
        params: dict[str, Any] = {"organisation_id": organisation_id, "limit": limit}
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status.value
        if after_id is not None:
            conditions.append("id < :after_id")
            params["after_id"] = after_id
        async with self._db.begin() as conn:
            rows = (
                await conn.execute(
                    sa.text(
                        f"SELECT {JOB_COLUMNS} FROM jobs WHERE {' AND '.join(conditions)} "
                        "ORDER BY id DESC LIMIT :limit"
                    ),
                    params,
                )
            ).all()
        return [job_record(row) for row in rows]

    async def list_attempts(
        self, *, organisation_id: uuid.UUID, job_id: uuid.UUID
    ) -> list[AttemptRecord] | None:
        async with self._db.begin() as conn:
            # job_attempts has no organisation column: isolation goes through the owning job row.
            owned = (
                await conn.execute(
                    sa.text("SELECT 1 FROM jobs WHERE id = :id AND organisation_id = :org"),
                    {"id": job_id, "org": organisation_id},
                )
            ).first()
            if owned is None:
                return None
            rows = (
                await conn.execute(
                    sa.text(
                        "SELECT id, job_id, attempt_number, worker_id, started_at, finished_at, "
                        "outcome, error, trace_id FROM job_attempts "
                        "WHERE job_id = :job_id ORDER BY attempt_number"
                    ),
                    {"job_id": job_id},
                )
            ).all()
        return [
            AttemptRecord(
                id=row.id,
                job_id=row.job_id,
                attempt_number=row.attempt_number,
                worker_id=row.worker_id,
                started_at=row.started_at,
                finished_at=row.finished_at,
                outcome=row.outcome,
                error=row.error,
                trace_id=row.trace_id,
            )
            for row in rows
        ]


async def _existing_for_key(
    conn: AsyncConnection, job: NewJob
) -> Existing | IdempotencyConflict | None:
    row = (
        await conn.execute(
            sa.text(
                f"SELECT {JOB_COLUMNS}, request_hash FROM jobs "
                "WHERE organisation_id = :organisation_id AND idempotency_key = :key"
            ),
            {"organisation_id": job.organisation_id, "key": job.idempotency_key},
        )
    ).first()
    if row is None:
        return None
    stored = None if row.request_hash is None else bytes(row.request_hash)
    if stored != job.request_hash:
        return IdempotencyConflict()
    return Existing(job_record(row))


async def _first_unavailable_file(conn: AsyncConnection, job: NewJob) -> uuid.UUID | None:
    wanted = list(dict.fromkeys(job.input_file_ids))
    if not wanted:
        return None
    rows = (
        await conn.execute(
            sa.text(
                "SELECT id, status, (expires_at IS NOT NULL AND expires_at <= now()) AS expired "
                "FROM files WHERE organisation_id = :organisation_id AND id = ANY(:ids) "
                "FOR SHARE"
            ).bindparams(sa.bindparam("ids", type_=postgresql.ARRAY(sa.Uuid))),
            {"organisation_id": job.organisation_id, "ids": wanted},
        )
    ).all()
    usable = {row.id for row in rows if row.status == "available" and not row.expired}
    for file_id in wanted:
        if file_id not in usable:
            return file_id
    return None
