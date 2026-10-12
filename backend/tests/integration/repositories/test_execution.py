"""The worker side of the jobs repository against a real PostgreSQL (spec FEAT-20261010-1211)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from qfe.adapters.postgres.execution import PostgresJobExecutionRepository
from qfe.adapters.postgres.jobs import PostgresJobRepository
from qfe.domain import JobEvent, JobStatus, source_statuses
from qfe.ports.repositories import (
    Claimed,
    LeaseLost,
    Ok,
    RefusalReason,
    Refused,
)
from tests.integration.repositories.conftest import (
    AccountFactory,
    AdminSql,
    FileFactory,
    set_job,
    submit_job_for,
)

LEASE = timedelta(seconds=60)
ERROR = {"code": "boom", "message": "it broke", "retryable": True}


async def claim(execution: PostgresJobExecutionRepository, job_id: uuid.UUID) -> Claimed:
    result = await execution.claim_job(job_id=job_id, worker_id="worker-1", lease=LEASE)
    assert isinstance(result, Claimed), result
    return result


# --- claim


async def test_a_claim_takes_the_job_with_a_lease_and_records_the_attempt(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    trace = uuid.uuid4().hex
    job_id = await submit_job_for(jobs, account, trace_id=trace, payload={"message": "go"})
    claimed = await claim(execution, job_id)

    assert claimed.job_id == job_id
    assert (claimed.attempt_number, claimed.attempts, claimed.max_attempts) == (1, 1, 4)
    assert claimed.organisation_id == account.organisation_id
    assert (claimed.job_type, claimed.type_version, claimed.trace_id) == ("echo", "1", trace)
    assert claimed.payload == {"message": "go"}

    row = (await admin.rows("SELECT * FROM jobs WHERE id = :i", i=job_id))[0]
    assert row.status == "running"
    assert (row.lease_owner, row.lease_token) == ("worker-1", claimed.lease_token)
    assert timedelta(seconds=55) < row.lease_expires_at - datetime.now(UTC) <= LEASE
    assert row.started_at is not None
    assert row.sweep_count == 0
    attempts = await admin.rows("SELECT * FROM job_attempts WHERE job_id = :j", j=job_id)
    assert len(attempts) == 1
    assert (attempts[0].attempt_number, attempts[0].worker_id) == (1, "worker-1")
    assert attempts[0].trace_id == trace
    assert attempts[0].finished_at is None


async def test_a_second_claim_of_a_running_job_is_refused(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
) -> None:
    job_id = await submit_job_for(jobs, await make_account())
    await claim(execution, job_id)
    again = await execution.claim_job(job_id=job_id, worker_id="worker-2", lease=LEASE)
    assert again == Refused(RefusalReason.NOT_CLAIMABLE, JobStatus.RUNNING)


async def test_refusal_reasons(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    assert await execution.claim_job(job_id=uuid.uuid4(), worker_id="w", lease=LEASE) == Refused(
        RefusalReason.NOT_FOUND
    )
    future = await submit_job_for(jobs, account)
    await admin.run("UPDATE jobs SET run_at = now() + interval '1 hour' WHERE id = :i", i=future)
    assert await execution.claim_job(job_id=future, worker_id="w", lease=LEASE) == Refused(
        RefusalReason.NOT_DUE, JobStatus.QUEUED
    )
    done = await submit_job_for(jobs, account)
    await set_job(admin, done, status="succeeded")
    assert await execution.claim_job(job_id=done, worker_id="w", lease=LEASE) == Refused(
        RefusalReason.NOT_CLAIMABLE, JobStatus.SUCCEEDED
    )


async def test_ten_simultaneous_claims_have_exactly_one_winner(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    job_id = await submit_job_for(jobs, await make_account())
    results = await asyncio.gather(
        *(execution.claim_job(job_id=job_id, worker_id=f"w{i}", lease=LEASE) for i in range(10))
    )
    assert sum(isinstance(r, Claimed) for r in results) == 1
    assert sum(isinstance(r, Refused) for r in results) == 9
    assert await admin.scalar("SELECT count(*) FROM job_attempts WHERE job_id = :j", j=job_id) == 1
    assert await admin.scalar("SELECT attempts FROM jobs WHERE id = :j", j=job_id) == 1


# --- heartbeat


async def test_a_heartbeat_extends_the_lease_and_sets_progress(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    job_id = await submit_job_for(jobs, await make_account())
    claimed = await claim(execution, job_id)
    before = await admin.scalar("SELECT lease_expires_at FROM jobs WHERE id = :i", i=job_id)
    result = await execution.heartbeat_job(
        job_id=job_id, lease_token=claimed.lease_token, lease=timedelta(minutes=10), progress=40
    )
    assert isinstance(result, Ok)
    row = (await admin.rows("SELECT lease_expires_at, progress FROM jobs WHERE id = :i", i=job_id))[
        0
    ]
    assert row.lease_expires_at > before + timedelta(minutes=5)
    assert row.progress == 40
    again = await execution.heartbeat_job(
        job_id=job_id, lease_token=claimed.lease_token, lease=LEASE, progress=None
    )
    assert isinstance(again, Ok)
    assert await admin.scalar("SELECT progress FROM jobs WHERE id = :i", i=job_id) == 40  # kept


async def test_a_heartbeat_with_the_wrong_token_is_lease_lost(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
) -> None:
    job_id = await submit_job_for(jobs, await make_account())
    await claim(execution, job_id)
    result = await execution.heartbeat_job(
        job_id=job_id, lease_token=uuid.uuid4(), lease=LEASE, progress=10
    )
    assert isinstance(result, LeaseLost)


@pytest.mark.parametrize("progress", [-1, 101])
async def test_progress_outside_zero_to_one_hundred_is_refused(
    execution: PostgresJobExecutionRepository, progress: int
) -> None:
    with pytest.raises(ValueError, match="progress"):
        await execution.heartbeat_job(
            job_id=uuid.uuid4(), lease_token=uuid.uuid4(), lease=LEASE, progress=progress
        )


# --- finish with success


async def test_finishing_stores_the_result_and_closes_the_attempt(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id = await submit_job_for(jobs, account)
    claimed = await claim(execution, job_id)
    result = await execution.finish_job_success(
        job_id=job_id,
        lease_token=claimed.lease_token,
        result={"message": "done", "attempt": 1},
        result_file_id=None,
    )
    assert isinstance(result, Ok)
    job = await jobs.get_job(organisation_id=account.organisation_id, job_id=job_id)
    assert job is not None
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == {"message": "done", "attempt": 1}
    assert (job.progress, job.finished_at is not None) == (100, True)
    assert await admin.scalar("SELECT lease_token FROM jobs WHERE id = :i", i=job_id) is None
    attempt = (
        await admin.rows(
            "SELECT outcome, finished_at FROM job_attempts WHERE job_id = :j", j=job_id
        )
    )[0]
    assert attempt.outcome == "succeeded"
    assert attempt.finished_at is not None
    # a duplicate finish from the same worker changes nothing
    again = await execution.finish_job_success(
        job_id=job_id, lease_token=claimed.lease_token, result={"x": 1}, result_file_id=None
    )
    assert isinstance(again, LeaseLost)


async def test_a_job_can_finish_with_a_result_file(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
) -> None:
    from qfe.ports.repositories import FileKind

    account = await make_account()
    job_id = await submit_job_for(jobs, account)
    claimed = await claim(execution, job_id)
    result_file = await make_file(account, kind=FileKind.RESULT)
    outcome = await execution.finish_job_success(
        job_id=job_id, lease_token=claimed.lease_token, result=None, result_file_id=result_file
    )
    assert isinstance(outcome, Ok)
    job = await jobs.get_job(organisation_id=account.organisation_id, job_id=job_id)
    assert job is not None
    assert (job.result, job.result_file_id) == (None, result_file)


async def test_a_result_and_a_result_file_together_are_refused(
    execution: PostgresJobExecutionRepository,
) -> None:
    with pytest.raises(ValueError, match="not both"):
        await execution.finish_job_success(
            job_id=uuid.uuid4(), lease_token=uuid.uuid4(), result={}, result_file_id=uuid.uuid4()
        )


# --- retry


async def test_a_retry_waits_for_its_delay_and_queues_one_message_for_the_same_time(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id = await submit_job_for(jobs, account)
    claimed = await claim(execution, job_id)
    result = await execution.retry_job(
        job_id=job_id,
        lease_token=claimed.lease_token,
        delay=timedelta(minutes=2),
        error=ERROR,
        outcome="retryable_error",
    )
    assert isinstance(result, Ok)
    job = await jobs.get_job(organisation_id=account.organisation_id, job_id=job_id)
    assert job is not None
    assert job.status is JobStatus.RETRYING
    assert job.error == ERROR
    assert timedelta(seconds=110) < job.run_at - datetime.now(UTC) <= timedelta(minutes=2)
    attempt = (
        await admin.rows("SELECT outcome, error FROM job_attempts WHERE job_id = :j", j=job_id)
    )[0]
    assert (attempt.outcome, attempt.error) == ("retryable_error", ERROR)
    messages = await admin.rows(
        "SELECT reason, routing_key, run_at, published_at FROM outbox "
        "WHERE job_id = :j ORDER BY id",
        j=job_id,
    )
    assert [m.reason for m in messages] == ["submit", "retry"]
    assert messages[1].routing_key == "echo"
    assert messages[1].run_at == job.run_at  # the message and the job agree on the time
    assert messages[1].published_at is None
    # not due yet, so a worker cannot take it early
    early = await execution.claim_job(job_id=job_id, worker_id="w", lease=LEASE)
    assert early == Refused(RefusalReason.NOT_DUE, JobStatus.RETRYING)
    # once due, the next claim is attempt number 2 with a new lease token
    await admin.run("UPDATE jobs SET run_at = now() - interval '1 second' WHERE id = :i", i=job_id)
    second = await claim(execution, job_id)
    assert second.attempt_number == 2
    assert second.lease_token != claimed.lease_token


async def test_a_retry_with_a_stale_token_changes_nothing(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    job_id = await submit_job_for(jobs, await make_account())
    await claim(execution, job_id)
    result = await execution.retry_job(
        job_id=job_id,
        lease_token=uuid.uuid4(),
        delay=timedelta(seconds=5),
        error=ERROR,
        outcome="timeout",
    )
    assert isinstance(result, LeaseLost)
    assert await admin.scalar("SELECT status FROM jobs WHERE id = :i", i=job_id) == "running"
    assert await admin.scalar("SELECT count(*) FROM outbox WHERE job_id = :j", j=job_id) == 1


# --- fail


async def test_a_failure_is_final_and_queues_no_message(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id = await submit_job_for(jobs, account)
    claimed = await claim(execution, job_id)
    result = await execution.fail_job(
        job_id=job_id,
        lease_token=claimed.lease_token,
        error={"code": "bad_input", "message": "unsupported", "retryable": False},
        outcome="permanent_error",
    )
    assert isinstance(result, Ok)
    job = await jobs.get_job(organisation_id=account.organisation_id, job_id=job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
    assert job.error is not None and job.error["code"] == "bad_input"
    assert job.finished_at is not None
    attempt = (await admin.rows("SELECT outcome FROM job_attempts WHERE job_id = :j", j=job_id))[0]
    assert attempt.outcome == "permanent_error"
    assert await admin.scalar("SELECT count(*) FROM outbox WHERE job_id = :j", j=job_id) == 1
    assert isinstance(
        await execution.fail_job(
            job_id=job_id, lease_token=claimed.lease_token, error=ERROR, outcome="retryable_error"
        ),
        LeaseLost,
    )


# --- the domain table decides every status guard

KNOWN_TOKEN = uuid.UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize("status", list(JobStatus))
@pytest.mark.parametrize("operation", ["claim", "heartbeat", "finish", "retry", "fail"])
async def test_each_operation_works_exactly_in_the_statuses_the_table_allows(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    make_account: AccountFactory,
    admin: AdminSql,
    status: JobStatus,
    operation: str,
) -> None:
    job_id = await submit_job_for(jobs, await make_account())
    await set_job(
        admin,
        job_id,
        status=status.value,
        lease_token=KNOWN_TOKEN,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    if operation == "claim":
        result = await execution.claim_job(job_id=job_id, worker_id="w", lease=LEASE)
        expected = status in source_statuses(JobEvent.CLAIM)
        assert isinstance(result, Claimed) is expected
        return
    if operation == "heartbeat":
        written = await execution.heartbeat_job(
            job_id=job_id, lease_token=KNOWN_TOKEN, lease=LEASE, progress=None
        )
        expected = status is JobStatus.RUNNING
    elif operation == "finish":
        written = await execution.finish_job_success(
            job_id=job_id, lease_token=KNOWN_TOKEN, result={}, result_file_id=None
        )
        expected = status in source_statuses(JobEvent.SUCCEED)
    elif operation == "retry":
        written = await execution.retry_job(
            job_id=job_id,
            lease_token=KNOWN_TOKEN,
            delay=timedelta(seconds=1),
            error=ERROR,
            outcome="retryable_error",
        )
        expected = status in source_statuses(JobEvent.RETRY)
    else:
        written = await execution.fail_job(
            job_id=job_id, lease_token=KNOWN_TOKEN, error=ERROR, outcome="retryable_error"
        )
        expected = status in source_statuses(JobEvent.FAIL)
    assert isinstance(written, Ok) is expected
    if not expected:
        assert await admin.scalar("SELECT status FROM jobs WHERE id = :i", i=job_id) == status.value
