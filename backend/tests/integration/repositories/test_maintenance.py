"""The maintenance chores against a real PostgreSQL (spec FEAT-20261010-1211)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from qfe.adapters.postgres.accounts import PostgresAccountRepository
from qfe.adapters.postgres.execution import PostgresJobExecutionRepository
from qfe.adapters.postgres.jobs import PostgresJobRepository
from qfe.adapters.postgres.maintenance import PostgresMaintenanceRepository
from qfe.domain import JobEvent
from qfe.ports.repositories import (
    Claimed,
    ExpiredLeaseJob,
    LeaseLost,
    Recovered,
)
from tests.integration.repositories.conftest import (
    Account,
    AccountFactory,
    AdminSql,
    FileFactory,
    set_job,
    submit_job_for,
)

LEASE = timedelta(seconds=60)
DELAY = timedelta(minutes=2)


def delay_of_two_minutes(job: ExpiredLeaseJob) -> timedelta:
    return DELAY


async def running_job_with_expired_lease(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    admin: AdminSql,
    account: Account,
    **overrides: object,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A claimed job whose lease ran out; returns the job id and the old worker's lease token."""
    job_id = await submit_job_for(jobs, account, **overrides)
    claimed = await execution.claim_job(job_id=job_id, worker_id="dead-worker", lease=LEASE)
    assert isinstance(claimed, Claimed)
    await set_job(admin, job_id, lease_expires_at=datetime.now(UTC) - timedelta(seconds=5))
    return job_id, claimed.lease_token


# --- lease recovery


async def test_a_job_whose_lease_ran_out_is_retried_after_the_delay(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id, _ = await running_job_with_expired_lease(jobs, execution, admin, account)
    seen: list[ExpiredLeaseJob] = []

    def delay_for(job: ExpiredLeaseJob) -> timedelta:
        seen.append(job)
        return DELAY

    recovered = await maintenance.recover_expired_leases(batch_size=10, delay_for=delay_for)
    assert recovered == [Recovered(job_id, JobEvent.RETRY)]
    assert seen == [ExpiredLeaseJob(job_id, "echo", 1, 4)]

    job = (await admin.rows("SELECT * FROM jobs WHERE id = :i", i=job_id))[0]
    assert job.status == "retrying"
    assert timedelta(seconds=110) < job.run_at - datetime.now(UTC) <= DELAY
    assert (job.lease_owner, job.lease_token, job.lease_expires_at) == (None, None, None)
    assert job.error["code"] == "lease_lost"
    assert job.error["retryable"] is True
    attempt = (
        await admin.rows(
            "SELECT outcome, finished_at FROM job_attempts WHERE job_id = :j", j=job_id
        )
    )[0]
    assert attempt.outcome == "lease_lost"
    assert attempt.finished_at is not None
    messages = await admin.rows(
        "SELECT reason, run_at FROM outbox WHERE job_id = :j ORDER BY id", j=job_id
    )
    assert [m.reason for m in messages] == ["submit", "recovery"]
    assert messages[1].run_at == job.run_at


async def test_a_job_with_no_tries_left_fails_without_asking_for_a_delay(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id, _ = await running_job_with_expired_lease(
        jobs, execution, admin, account, max_attempts=1
    )

    def never(job: ExpiredLeaseJob) -> timedelta:
        raise AssertionError("no delay is needed for a job that fails")

    recovered = await maintenance.recover_expired_leases(batch_size=10, delay_for=never)
    assert recovered == [Recovered(job_id, JobEvent.FAIL)]
    job = (await admin.rows("SELECT status, finished_at, error FROM jobs WHERE id = :i", i=job_id))[
        0
    ]
    assert job.status == "failed"
    assert job.finished_at is not None
    assert job.error["retryable"] is False
    assert await admin.scalar("SELECT count(*) FROM outbox WHERE job_id = :j", j=job_id) == 1
    outcome = await admin.scalar("SELECT outcome FROM job_attempts WHERE job_id = :j", j=job_id)
    assert outcome == "lease_lost"


async def test_jobs_with_a_live_lease_or_another_status_are_left_alone(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    alive = await submit_job_for(jobs, account)
    await execution.claim_job(job_id=alive, worker_id="w", lease=LEASE)  # lease runs for a minute
    waiting = await submit_job_for(jobs, account)
    done = await submit_job_for(jobs, account)
    await set_job(
        admin, done, status="succeeded", lease_expires_at=datetime.now(UTC) - timedelta(hours=1)
    )
    assert (
        await maintenance.recover_expired_leases(batch_size=10, delay_for=delay_of_two_minutes)
        == []
    )
    assert await admin.scalar("SELECT status FROM jobs WHERE id = :i", i=alive) == "running"
    assert await admin.scalar("SELECT status FROM jobs WHERE id = :i", i=waiting) == "queued"


async def test_recovery_handles_at_most_one_batch(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    for _ in range(5):
        await running_job_with_expired_lease(jobs, execution, admin, account)
    first = await maintenance.recover_expired_leases(batch_size=2, delay_for=delay_of_two_minutes)
    assert len(first) == 2
    rest = await maintenance.recover_expired_leases(batch_size=10, delay_for=delay_of_two_minutes)
    assert len(rest) == 3


async def test_five_maintenance_copies_recover_each_job_exactly_once(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    ids = {
        (await running_job_with_expired_lease(jobs, execution, admin, account))[0] for _ in range(8)
    }
    batches = await asyncio.gather(
        *(
            maintenance.recover_expired_leases(batch_size=20, delay_for=delay_of_two_minutes)
            for _ in range(5)
        )
    )
    recovered = [item.job_id for batch in batches for item in batch]
    assert sorted(recovered) == sorted(ids)  # every job once, none twice
    assert await admin.scalar("SELECT count(*) FROM outbox WHERE reason = 'recovery'") == 8


async def test_the_old_worker_can_no_longer_write_after_recovery(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id, old_token = await running_job_with_expired_lease(jobs, execution, admin, account)
    await maintenance.recover_expired_leases(batch_size=10, delay_for=delay_of_two_minutes)
    await set_job(admin, job_id, run_at=datetime.now(UTC) - timedelta(seconds=1))
    newer = await execution.claim_job(job_id=job_id, worker_id="new-worker", lease=LEASE)
    assert isinstance(newer, Claimed)
    assert newer.attempt_number == 2

    heartbeat = await execution.heartbeat_job(
        job_id=job_id, lease_token=old_token, lease=LEASE, progress=99
    )
    finish = await execution.finish_job_success(
        job_id=job_id, lease_token=old_token, result={"late": True}, result_file_id=None
    )
    retry = await execution.retry_job(
        job_id=job_id, lease_token=old_token, delay=DELAY, error={}, outcome="timeout"
    )
    fail = await execution.fail_job(
        job_id=job_id, lease_token=old_token, error={}, outcome="timeout"
    )
    assert all(isinstance(r, LeaseLost) for r in (heartbeat, finish, retry, fail))
    row = (await admin.rows("SELECT status, progress, result FROM jobs WHERE id = :i", i=job_id))[0]
    assert (row.status, row.progress, row.result) == (
        "running",
        0,
        None,
    )  # the newer attempt is untouched


async def test_a_job_that_crashes_every_worker_fails_after_max_attempts(
    jobs: PostgresJobRepository,
    execution: PostgresJobExecutionRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    """The crash-loop guarantee, end to end: claim, lose the lease, recover, repeat."""
    account = await make_account()
    job_id = await submit_job_for(jobs, account, max_attempts=3)
    claims = 0
    while True:
        await set_job(admin, job_id, run_at=datetime.now(UTC) - timedelta(seconds=1))
        claimed = await execution.claim_job(job_id=job_id, worker_id="crashy", lease=LEASE)
        if not isinstance(claimed, Claimed):
            break
        claims += 1
        await set_job(admin, job_id, lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        await maintenance.recover_expired_leases(batch_size=5, delay_for=delay_of_two_minutes)
    assert claims == 3
    row = (await admin.rows("SELECT status, attempts FROM jobs WHERE id = :i", i=job_id))[0]
    assert (row.status, row.attempts) == ("failed", 3)
    outcomes = await admin.rows("SELECT outcome FROM job_attempts WHERE job_id = :j", j=job_id)
    assert [o.outcome for o in outcomes] == ["lease_lost"] * 3


# --- the safety-net sweep ---

BASE = timedelta(minutes=5)
CAP = timedelta(hours=1)


async def waiting_job(
    jobs: PostgresJobRepository,
    admin: AdminSql,
    account: Account,
    *,
    minutes_idle: float,
    sweep_count: int = 0,
    status: str = "queued",
    keep_outbox_row: bool = False,
) -> uuid.UUID:
    """A job that has waited ``minutes_idle`` with its message already published and gone."""
    job_id = await submit_job_for(jobs, account)
    idle = datetime.now(UTC) - timedelta(minutes=minutes_idle)
    await set_job(
        admin,
        job_id,
        status=status,
        run_at=idle,
        last_enqueued_at=idle,
        sweep_count=sweep_count,
    )
    if not keep_outbox_row:
        await admin.run("UPDATE outbox SET published_at = now() WHERE job_id = :j", j=job_id)
    return job_id


async def sweep(maintenance: PostgresMaintenanceRepository, batch: int = 50) -> list[uuid.UUID]:
    return await maintenance.sweep_waiting_jobs(batch_size=batch, base_wait=BASE, max_wait=CAP)


async def test_a_lost_job_gets_a_new_message_and_the_wait_grows(
    jobs: PostgresJobRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id = await waiting_job(jobs, admin, account, minutes_idle=6)
    assert await sweep(maintenance) == [job_id]
    row = (
        await admin.rows("SELECT sweep_count, last_enqueued_at FROM jobs WHERE id = :i", i=job_id)
    )[0]
    assert row.sweep_count == 1
    assert datetime.now(UTC) - row.last_enqueued_at < timedelta(minutes=1)
    reasons = await admin.rows("SELECT reason FROM outbox WHERE job_id = :j ORDER BY id", j=job_id)
    assert [r.reason for r in reasons] == ["submit", "sweep"]
    assert await sweep(maintenance) == []  # a fresh message is on its way


async def test_the_wait_is_five_minutes_doubling_and_capped_at_one_hour(
    jobs: PostgresJobRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    cases = [
        # (times swept already, minutes idle, swept now?)
        (0, 4.5, False),
        (0, 5.5, True),
        (1, 9, False),
        (1, 11, True),
        (2, 19, False),
        (2, 21, True),
        (3, 39, False),
        (3, 41, True),
        (4, 79, True),  # 80 minutes would be due, but the cap is 60
        (4, 59, False),
        (10, 61, True),
        (10, 59, False),
    ]
    for count, idle, expected in cases:
        job_id = await waiting_job(jobs, admin, account, minutes_idle=idle, sweep_count=count)
        swept = await sweep(maintenance)
        assert (job_id in swept) is expected, (count, idle)
        # settle the job so it does not take part in the next case
        await set_job(admin, job_id, status="succeeded")


async def test_jobs_with_an_unpublished_message_or_another_status_are_not_swept(
    jobs: PostgresJobRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    await waiting_job(jobs, admin, account, minutes_idle=30, keep_outbox_row=True)
    await waiting_job(jobs, admin, account, minutes_idle=30, status="running")
    await waiting_job(jobs, admin, account, minutes_idle=30, status="failed")
    retrying = await waiting_job(jobs, admin, account, minutes_idle=30, status="retrying")
    assert await sweep(maintenance) == [retrying]  # a retrying job waiting too long is swept


async def test_deleting_old_outbox_rows_never_resets_the_wait(
    jobs: PostgresJobRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    job_id = await waiting_job(jobs, admin, account, minutes_idle=8, sweep_count=1)
    await admin.run("DELETE FROM outbox WHERE job_id = :j", j=job_id)
    assert await sweep(maintenance) == []  # still inside the 10 minute wait for a second sweep


async def test_the_sweep_handles_at_most_one_batch(
    jobs: PostgresJobRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    for _ in range(4):
        await waiting_job(jobs, admin, account, minutes_idle=10)
    assert len(await sweep(maintenance, batch=3)) == 3
    assert len(await sweep(maintenance, batch=3)) == 1


# --- cleanups and purge


async def test_published_outbox_rows_are_deleted_after_the_age_and_unpublished_ones_kept(
    jobs: PostgresJobRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    ids = [await submit_job_for(jobs, account) for _ in range(4)]
    await admin.run(
        "UPDATE outbox SET published_at = now() - interval '2 days' WHERE job_id = ANY(:ids)",
        ids=ids[:2],
    )
    await admin.run("UPDATE outbox SET published_at = now() WHERE job_id = :j", j=ids[2])
    deleted = await maintenance.cleanup_published_outbox(
        older_than=timedelta(hours=24), batch_size=1
    )
    assert deleted == 1  # one batch
    deleted += await maintenance.cleanup_published_outbox(
        older_than=timedelta(hours=24), batch_size=10
    )
    assert deleted == 2
    remaining = await admin.scalar("SELECT count(*) FROM outbox")
    assert remaining == 2  # the recent published row and the unpublished one


async def test_refresh_tokens_are_cleaned_after_a_grace_period(
    accounts: PostgresAccountRepository,
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    tokens = [
        await accounts.start_login_session(
            user_id=account.user_id,
            token_lifetime=timedelta(days=1),
            family_lifetime=timedelta(days=30),
            ip=None,
            user_agent=None,
        )
        for _ in range(4)
    ]
    await admin.run(
        "UPDATE refresh_tokens SET expires_at = now() - interval '3 days' WHERE id = :i",
        i=tokens[0].id,
    )
    await admin.run(
        "UPDATE refresh_tokens SET revoked_at = now() - interval '3 days' WHERE id = :i",
        i=tokens[1].id,
    )
    await admin.run(
        "UPDATE refresh_tokens SET expires_at = now() - interval '1 hour' WHERE id = :i",
        i=tokens[2].id,
    )  # expired, but inside the grace period
    deleted = await maintenance.cleanup_refresh_tokens(grace=timedelta(days=1), batch_size=10)
    assert deleted == 2
    left = {row.id for row in await admin.rows("SELECT id FROM refresh_tokens")}
    assert left == {tokens[2].id, tokens[3].id}


async def test_unused_uploads_are_deleted_and_their_keys_returned(
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    stale = await make_file(account, available=False)
    fresh = await make_file(account, available=False)
    available = await make_file(account)
    await admin.run(
        "UPDATE files SET expires_at = now() - interval '1 minute' WHERE id = ANY(:ids)",
        ids=[stale, available],
    )
    stale_key = await admin.scalar("SELECT storage_key FROM files WHERE id = :i", i=stale)
    assert await maintenance.cleanup_pending_files(batch_size=10) == [stale_key]
    left = {row.id for row in await admin.rows("SELECT id FROM files")}
    assert left == {fresh, available}  # an available file is never an unused upload


async def insert_old_job(
    admin: AdminSql, account: Account, *, status: str, days_old: int
) -> uuid.UUID:
    """A job whose id (and so its age) says it was made ``days_old`` days ago."""
    job_id = await admin.insert_returning(
        "INSERT INTO jobs (id, organisation_id, type, type_version, status, payload, "
        "max_attempts, trace_id) "
        "VALUES (uuidv7(make_interval(days => -CAST(:days AS integer))), :org, 'echo', "
        "'1', :status, '{}', 3, :trace) RETURNING id",
        days=days_old,
        org=account.organisation_id,
        status=status,
        trace=uuid.uuid4().hex,
    )
    assert isinstance(job_id, uuid.UUID)
    return job_id


async def test_purge_removes_only_old_jobs_in_a_final_state_and_their_children(
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    old_final = [
        await insert_old_job(admin, account, status=status, days_old=40)
        for status in ("succeeded", "failed", "cancelled")
    ]
    old_live = [
        await insert_old_job(admin, account, status=status, days_old=40)
        for status in ("queued", "retrying", "running")
    ]
    young_final = await insert_old_job(admin, account, status="succeeded", days_old=1)
    file_id = await make_file(account)
    await admin.run(
        "INSERT INTO job_files (job_id, file_id) VALUES (:j, :f)", j=old_final[0], f=file_id
    )
    await admin.run(
        "INSERT INTO job_attempts (job_id, attempt_number, started_at) VALUES (:j, 1, now())",
        j=old_final[0],
    )
    await admin.run(
        "INSERT INTO outbox (job_id, routing_key, reason, headers, body) "
        "VALUES (:j, 'echo', 'submit', '{}', '{}')",
        j=old_final[0],
    )

    deleted = await maintenance.purge_finished_jobs(older_than=timedelta(days=30), batch_size=100)
    assert deleted == 3
    left = {row.id for row in await admin.rows("SELECT id FROM jobs")}
    assert left == {*old_live, young_final}
    # the children went with the job; the file itself stays (it is not removed with the job)
    assert await admin.scalar("SELECT count(*) FROM job_attempts") == 0
    assert await admin.scalar("SELECT count(*) FROM outbox") == 0
    assert await admin.scalar("SELECT count(*) FROM job_files") == 0
    assert await admin.scalar("SELECT count(*) FROM files WHERE id = :f", f=file_id) == 1


async def test_purge_goes_in_batches_oldest_first(
    maintenance: PostgresMaintenanceRepository,
    make_account: AccountFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    oldest = await insert_old_job(admin, account, status="failed", days_old=90)
    middle = await insert_old_job(admin, account, status="failed", days_old=60)
    newest_old = await insert_old_job(admin, account, status="failed", days_old=40)
    assert await maintenance.purge_finished_jobs(older_than=timedelta(days=30), batch_size=1) == 1
    left = {row.id for row in await admin.rows("SELECT id FROM jobs")}
    assert left == {middle, newest_old}  # the oldest went first
    assert oldest not in left
    assert await maintenance.purge_finished_jobs(older_than=timedelta(days=30), batch_size=10) == 2
