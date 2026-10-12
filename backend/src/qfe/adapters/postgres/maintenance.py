"""Background chores: lease recovery, the safety-net sweep, cleanups and purge.

Each recovered or swept job is its own transaction, claimed with ``FOR UPDATE SKIP LOCKED``, so
several maintenance copies can run at once and a crash between jobs leaves the rest for the next
run. Retry-or-fail is decided by the same domain function the worker uses.
"""

import json
import uuid
from collections.abc import Callable
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from qfe.adapters.postgres.database import Database, seconds
from qfe.adapters.postgres.execution import insert_outbox_row, status_list
from qfe.domain import (
    FINAL_STATUSES,
    JobEvent,
    JobStatus,
    decide_after_failure,
    next_status,
)
from qfe.ports.repositories import ExpiredLeaseJob, Recovered

_FINAL_SQL = ", ".join(f"'{status.value}'" for status in sorted(FINAL_STATUSES))
_LEASE_LOST = "lease_lost"


class PostgresMaintenanceRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def recover_expired_leases(
        self, *, batch_size: int, delay_for: Callable[[ExpiredLeaseJob], timedelta]
    ) -> list[Recovered]:
        async with self._db.begin() as conn:
            candidates = (
                await conn.execute(
                    sa.text(
                        "SELECT id FROM jobs WHERE status = 'running' AND lease_expires_at < now() "
                        "ORDER BY id LIMIT :batch"
                    ),
                    {"batch": batch_size},
                )
            ).all()
        recovered: list[Recovered] = []
        for candidate in candidates:
            async with self._db.begin() as conn:
                outcome = await self._recover_one(conn, candidate.id, delay_for)
            if outcome is not None:
                recovered.append(outcome)
        return recovered

    async def _recover_one(
        self,
        conn: AsyncConnection,
        job_id: uuid.UUID,
        delay_for: Callable[[ExpiredLeaseJob], timedelta],
    ) -> Recovered | None:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT id, type, attempts, max_attempts, trace_id FROM jobs "
                    "WHERE id = :id AND status = 'running' AND lease_expires_at < now() "
                    "FOR UPDATE SKIP LOCKED"
                ),
                {"id": job_id},
            )
        ).first()
        if row is None:  # someone else got it, or it finished in the meantime
            return None
        decision = decide_after_failure(row.attempts, row.max_attempts, permanent=False)
        new_status = next_status(JobStatus.RUNNING, decision).value
        will_retry = decision is JobEvent.RETRY
        error = json.dumps(
            {
                "code": _LEASE_LOST,
                "message": "The worker stopped before the job finished.",
                "retryable": will_retry,
            }
        )
        guard = f"WHERE id = :id AND status IN ({status_list(decision)})"
        cleared = (
            "lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now()"
        )
        run_at = None
        if will_retry:
            delay = delay_for(ExpiredLeaseJob(row.id, row.type, row.attempts, row.max_attempts))
            updated = (
                await conn.execute(
                    sa.text(
                        f"UPDATE jobs SET status = '{new_status}', error = CAST(:error AS jsonb), "
                        "run_at = now() + make_interval(secs => :delay), "
                        f"last_enqueued_at = now(), {cleared} {guard} RETURNING run_at"
                    ),
                    {"id": job_id, "error": error, "delay": seconds(delay)},
                )
            ).one()
            run_at = updated.run_at
        else:
            await conn.execute(
                sa.text(
                    f"UPDATE jobs SET status = '{new_status}', error = CAST(:error AS jsonb), "
                    f"finished_at = now(), {cleared} {guard}"
                ),
                {"id": job_id, "error": error},
            )
        await conn.execute(
            sa.text(
                "UPDATE job_attempts SET finished_at = now(), outcome = :outcome, "
                "error = CAST(:error AS jsonb) "
                "WHERE job_id = :job_id AND attempt_number = :number AND finished_at IS NULL"
            ),
            {
                "job_id": job_id,
                "number": row.attempts,
                "outcome": _LEASE_LOST,
                "error": error,
            },
        )
        if will_retry:
            await insert_outbox_row(
                conn,
                job_id=job_id,
                routing_key=row.type,
                reason="recovery",
                trace_id=row.trace_id,
                run_at=run_at,
            )
        return Recovered(job_id=job_id, decision=decision)

    async def sweep_waiting_jobs(
        self, *, batch_size: int, base_wait: timedelta, max_wait: timedelta
    ) -> list[uuid.UUID]:
        # wait = base * 2^sweep_count, capped. The history lives on the job (sweep_count and
        # last_enqueued_at), so deleting old outbox rows can never reset the wait.
        wait = (
            "least(make_interval(secs => :base * power(2, j.sweep_count)), "
            "make_interval(secs => :cap))"
        )
        params = {"base": seconds(base_wait), "cap": seconds(max_wait)}
        async with self._db.begin() as conn:
            candidates = (
                await conn.execute(
                    sa.text(
                        "SELECT j.id FROM jobs j "
                        f"WHERE j.status IN ({status_list(JobEvent.CLAIM)}) "
                        f"AND j.run_at < now() - {wait} AND j.last_enqueued_at < now() - {wait} "
                        "AND NOT EXISTS (SELECT 1 FROM outbox o "
                        "                WHERE o.job_id = j.id AND o.published_at IS NULL) "
                        "ORDER BY j.id LIMIT :batch"
                    ),
                    {**params, "batch": batch_size},
                )
            ).all()
        swept: list[uuid.UUID] = []
        for candidate in candidates:
            async with self._db.begin() as conn:
                row = (
                    await conn.execute(
                        sa.text(
                            "UPDATE jobs j SET sweep_count = j.sweep_count + 1, "
                            "last_enqueued_at = now(), updated_at = now() "
                            "WHERE j.id = (SELECT id FROM jobs WHERE id = :id "
                            f"  AND status IN ({status_list(JobEvent.CLAIM)}) "
                            f"  AND run_at < now() - {wait} AND last_enqueued_at < now() - {wait} "
                            "  FOR UPDATE SKIP LOCKED) "
                            "RETURNING j.type, j.trace_id"
                        ),
                        {"id": candidate.id, **params},
                    )
                ).first()
                if row is None:
                    continue
                await insert_outbox_row(
                    conn,
                    job_id=candidate.id,
                    routing_key=row.type,
                    reason="sweep",
                    trace_id=row.trace_id,
                )
            swept.append(candidate.id)
        return swept

    async def cleanup_published_outbox(self, *, older_than: timedelta, batch_size: int) -> int:
        return await self._delete_count(
            "DELETE FROM outbox WHERE id IN (SELECT id FROM outbox WHERE published_at IS NOT NULL "
            "AND published_at < now() - make_interval(secs => :age) "
            "ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED)",
            {"age": seconds(older_than), "batch": batch_size},
        )

    async def cleanup_refresh_tokens(self, *, grace: timedelta, batch_size: int) -> int:
        return await self._delete_count(
            "DELETE FROM refresh_tokens WHERE id IN (SELECT id FROM refresh_tokens WHERE "
            "expires_at < now() - make_interval(secs => :grace) OR "
            "revoked_at < now() - make_interval(secs => :grace) "
            "ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED)",
            {"grace": seconds(grace), "batch": batch_size},
        )

    async def cleanup_pending_files(self, *, batch_size: int) -> list[str]:
        async with self._db.begin() as conn:
            rows = (
                await conn.execute(
                    sa.text(
                        "DELETE FROM files WHERE id IN (SELECT id FROM files "
                        "WHERE status = 'pending' AND expires_at < now() "
                        "ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED) RETURNING storage_key"
                    ),
                    {"batch": batch_size},
                )
            ).all()
        return [row.storage_key for row in rows]

    async def purge_finished_jobs(self, *, older_than: timedelta, batch_size: int) -> int:
        # Ids are time-ordered, so "older than" is an id range: cheap, and only final states go.
        return await self._delete_count(
            f"DELETE FROM jobs WHERE id IN (SELECT id FROM jobs WHERE status IN ({_FINAL_SQL}) "
            "AND id < uuidv7(make_interval(secs => -CAST(:age AS double precision))) "
            "ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED)",
            {"age": seconds(older_than), "batch": batch_size},
        )

    async def _delete_count(self, sql: str, params: dict[str, object]) -> int:
        async with self._db.begin() as conn:
            result = await conn.execute(sa.text(sql), params)
        return int(result.rowcount)
