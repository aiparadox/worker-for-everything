"""Submit, read, list and attempts against a real PostgreSQL (spec FEAT-20261010-1211)."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from qfe.adapters.postgres.jobs import PostgresJobRepository
from qfe.domain import JobStatus
from qfe.ports.repositories import (
    CapExceeded,
    Created,
    Existing,
    FileUnavailable,
    IdempotencyConflict,
)
from tests.integration.repositories.conftest import (
    AccountFactory,
    AdminSql,
    FileFactory,
    new_job,
)


def hash_of(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()


async def submit_ok(jobs: PostgresJobRepository, account, **overrides) -> uuid.UUID:  # type: ignore[no-untyped-def]
    result = await jobs.submit_job(new_job(account, **overrides))
    assert isinstance(result, Created), result
    return result.job_id


# --- what a submit writes


async def test_a_submit_writes_the_job_the_file_links_and_one_outbox_row_together(
    jobs: PostgresJobRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    first, second = await make_file(account), await make_file(account)
    trace = uuid.uuid4().hex
    job_id = await submit_ok(
        jobs,
        account,
        trace_id=trace,
        input_file_ids=[first, second, first],  # a repeated id is linked once
        payload={"message": "hi", "nested": {"a": [1, 2]}},
        max_attempts=3,
    )
    job = await jobs.get_job(organisation_id=account.organisation_id, job_id=job_id)
    assert job is not None
    assert job.status is JobStatus.QUEUED
    assert (job.attempts, job.max_attempts, job.progress) == (0, 3, 0)
    assert (job.job_type, job.type_version, job.trace_id) == ("echo", "1", trace)
    assert job.payload == {"message": "hi", "nested": {"a": [1, 2]}}
    assert abs((job.run_at - datetime.now(UTC)).total_seconds()) < 30
    links = await admin.rows("SELECT file_id FROM job_files WHERE job_id = :j", j=job_id)
    assert {row.file_id for row in links} == {first, second}
    outbox = await admin.rows(
        "SELECT routing_key, reason, headers, body, published_at, run_at "
        "FROM outbox WHERE job_id = :j",
        j=job_id,
    )
    assert len(outbox) == 1
    assert (outbox[0].routing_key, outbox[0].reason) == ("echo", "submit")
    assert outbox[0].headers == {"trace_id": trace}
    assert outbox[0].body == {"job_id": str(job_id)}
    assert outbox[0].published_at is None
    assert outbox[0].run_at == job.run_at


async def test_a_failed_insert_leaves_nothing_behind_and_frees_the_lock(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    with pytest.raises(IntegrityError):
        await jobs.submit_job(new_job(account, max_attempts=0))  # breaks the database check
    assert await admin.scalar("SELECT count(*) FROM jobs") == 0
    assert await admin.scalar("SELECT count(*) FROM outbox") == 0
    await submit_ok(jobs, account)  # the organisation lock was released with the rollback


# --- reading


async def test_a_job_is_only_visible_to_its_own_organisation(
    jobs: PostgresJobRepository, make_account: AccountFactory
) -> None:
    mine = await make_account()
    other = await make_account()
    job_id = await submit_ok(jobs, mine)
    assert await jobs.get_job(organisation_id=mine.organisation_id, job_id=job_id)
    assert await jobs.get_job(organisation_id=other.organisation_id, job_id=job_id) is None
    assert await jobs.get_job(organisation_id=mine.organisation_id, job_id=uuid.uuid4()) is None


async def test_listing_is_newest_first_filtered_by_status_and_paged_by_keyset(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    ids = [await submit_ok(jobs, account) for _ in range(7)]
    await admin.run("UPDATE jobs SET status = 'failed' WHERE id = ANY(:ids)", ids=[ids[0], ids[3]])
    everything = await jobs.list_jobs(
        organisation_id=account.organisation_id, status=None, after_id=None, limit=100
    )
    assert [job.id for job in everything] == list(reversed(ids))

    failed = await jobs.list_jobs(
        organisation_id=account.organisation_id, status=JobStatus.FAILED, after_id=None, limit=100
    )
    assert [job.id for job in failed] == [ids[3], ids[0]]

    seen: list[uuid.UUID] = []
    cursor = None
    while True:
        page = await jobs.list_jobs(
            organisation_id=account.organisation_id, status=None, after_id=cursor, limit=3
        )
        if not page:
            break
        seen.extend(job.id for job in page)
        cursor = page[-1].id
    assert seen == list(reversed(ids))  # no gap, no overlap


async def test_listing_never_shows_another_organisations_jobs(
    jobs: PostgresJobRepository, make_account: AccountFactory
) -> None:
    mine = await make_account()
    other = await make_account()
    await submit_ok(jobs, mine)
    await submit_ok(jobs, other)
    listed = await jobs.list_jobs(
        organisation_id=mine.organisation_id, status=None, after_id=None, limit=100
    )
    assert len(listed) == 1
    assert listed[0].organisation_id == mine.organisation_id


async def test_the_list_limit_is_checked(jobs: PostgresJobRepository) -> None:
    with pytest.raises(ValueError, match="limit"):
        await jobs.list_jobs(organisation_id=uuid.uuid4(), status=None, after_id=None, limit=0)


async def test_attempts_are_listed_in_order_and_only_for_the_owner(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    mine = await make_account()
    other = await make_account()
    job_id = await submit_ok(jobs, mine)
    assert await jobs.list_attempts(organisation_id=mine.organisation_id, job_id=job_id) == []
    for number in (2, 1):
        await admin.run(
            "INSERT INTO job_attempts (job_id, attempt_number, worker_id, started_at) "
            "VALUES (:j, :n, 'w1', now())",
            j=job_id,
            n=number,
        )
    attempts = await jobs.list_attempts(organisation_id=mine.organisation_id, job_id=job_id)
    assert attempts is not None
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert await jobs.list_attempts(organisation_id=other.organisation_id, job_id=job_id) is None
    assert (
        await jobs.list_attempts(organisation_id=mine.organisation_id, job_id=uuid.uuid4()) is None
    )


# --- idempotency


async def test_the_same_key_and_request_gives_back_the_first_job(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    request = hash_of("echo hello")
    first = await jobs.submit_job(new_job(account, idempotency_key="k-1", request_hash=request))
    assert isinstance(first, Created)
    again = await jobs.submit_job(new_job(account, idempotency_key="k-1", request_hash=request))
    assert isinstance(again, Existing)
    assert again.job.id == first.job_id
    assert await admin.scalar("SELECT count(*) FROM jobs") == 1
    assert await admin.scalar("SELECT count(*) FROM outbox") == 1


async def test_the_same_key_with_a_different_request_is_a_conflict(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    await jobs.submit_job(new_job(account, idempotency_key="k-2", request_hash=hash_of("a")))
    result = await jobs.submit_job(
        new_job(account, idempotency_key="k-2", request_hash=hash_of("b"))
    )
    assert isinstance(result, IdempotencyConflict)
    assert await admin.scalar("SELECT count(*) FROM jobs") == 1


async def test_keys_are_per_organisation_and_no_key_means_no_deduplication(
    jobs: PostgresJobRepository, make_account: AccountFactory
) -> None:
    one = await make_account()
    two = await make_account()
    request = hash_of("same")
    assert isinstance(
        await jobs.submit_job(new_job(one, idempotency_key="shared", request_hash=request)), Created
    )
    assert isinstance(
        await jobs.submit_job(new_job(two, idempotency_key="shared", request_hash=request)), Created
    )
    a = await submit_ok(jobs, one)
    b = await submit_ok(jobs, one)
    assert a != b


async def test_twenty_simultaneous_submits_with_one_key_make_one_job(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    request = hash_of("race")
    results = await asyncio.gather(
        *(
            jobs.submit_job(new_job(account, idempotency_key="race", request_hash=request))
            for _ in range(20)
        )
    )
    created = [r for r in results if isinstance(r, Created)]
    existing = [r for r in results if isinstance(r, Existing)]
    assert len(created) == 1
    assert len(existing) == 19
    assert {r.job.id for r in existing} == {created[0].job_id}
    assert await admin.scalar("SELECT count(*) FROM jobs") == 1
    assert await admin.scalar("SELECT count(*) FROM outbox") == 1


# --- the active jobs cap


async def test_twenty_simultaneous_submits_never_exceed_a_cap_of_five(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    results = await asyncio.gather(
        *(jobs.submit_job(new_job(account, active_jobs_cap=5)) for _ in range(20))
    )
    assert sum(isinstance(r, Created) for r in results) == 5
    assert sum(isinstance(r, CapExceeded) for r in results) == 15
    assert await admin.scalar("SELECT count(*) FROM jobs") == 5
    assert await admin.scalar("SELECT count(*) FROM outbox") == 5


async def test_finished_jobs_do_not_count_and_other_organisations_do_not_interfere(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    mine = await make_account()
    other = await make_account()
    ids = [await submit_ok(jobs, mine, active_jobs_cap=3) for _ in range(3)]
    assert isinstance(await jobs.submit_job(new_job(mine, active_jobs_cap=3)), CapExceeded)
    assert isinstance(await jobs.submit_job(new_job(other, active_jobs_cap=3)), Created)
    await admin.run("UPDATE jobs SET status = 'succeeded' WHERE id = :i", i=ids[0])
    assert isinstance(await jobs.submit_job(new_job(mine, active_jobs_cap=3)), Created)
    assert isinstance(await jobs.submit_job(new_job(mine, active_jobs_cap=3)), CapExceeded)


@pytest.mark.parametrize("status", ["queued", "retrying", "running"])
async def test_live_jobs_count_toward_the_cap(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql, status: str
) -> None:
    account = await make_account()
    job_id = await submit_ok(jobs, account, active_jobs_cap=1)
    await admin.run("UPDATE jobs SET status = :s WHERE id = :i", s=status, i=job_id)
    assert isinstance(await jobs.submit_job(new_job(account, active_jobs_cap=1)), CapExceeded)


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
async def test_final_jobs_do_not_count_toward_the_cap(
    jobs: PostgresJobRepository, make_account: AccountFactory, admin: AdminSql, status: str
) -> None:
    account = await make_account()
    job_id = await submit_ok(jobs, account, active_jobs_cap=1)
    await admin.run("UPDATE jobs SET status = :s WHERE id = :i", s=status, i=job_id)
    assert isinstance(await jobs.submit_job(new_job(account, active_jobs_cap=1)), Created)


# --- input files


async def test_a_pending_file_is_unavailable(
    jobs: PostgresJobRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    pending = await make_file(account, available=False)
    result = await jobs.submit_job(new_job(account, input_file_ids=[pending]))
    assert result == FileUnavailable(pending)
    assert await admin.scalar("SELECT count(*) FROM jobs") == 0
    assert await admin.scalar("SELECT count(*) FROM outbox") == 0


async def test_another_organisations_file_and_a_missing_file_are_unavailable(
    jobs: PostgresJobRepository, make_account: AccountFactory, make_file: FileFactory
) -> None:
    mine = await make_account()
    other = await make_account()
    theirs = await make_file(other)
    missing = uuid.uuid4()
    assert await jobs.submit_job(new_job(mine, input_file_ids=[theirs])) == FileUnavailable(theirs)
    assert await jobs.submit_job(new_job(mine, input_file_ids=[missing])) == FileUnavailable(
        missing
    )


async def test_an_expired_file_is_unavailable_and_the_first_bad_id_is_named(
    jobs: PostgresJobRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    good = await make_file(account)
    stale = await make_file(account)
    await admin.run(
        "UPDATE files SET expires_at = now() - interval '1 minute' WHERE id = :i", i=stale
    )
    missing = uuid.uuid4()
    result = await jobs.submit_job(new_job(account, input_file_ids=[good, stale, missing]))
    assert result == FileUnavailable(stale)


async def test_a_file_that_a_job_uses_cannot_be_deleted(
    jobs: PostgresJobRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
    admin: AdminSql,
) -> None:
    account = await make_account()
    file_id = await make_file(account)
    await submit_ok(jobs, account, input_file_ids=[file_id])
    # the database refuses to delete a file that a job uses
    with pytest.raises(IntegrityError):
        await admin.run("DELETE FROM files WHERE id = :i", i=file_id)


async def test_the_clock_of_this_process_changes_nothing(
    jobs: PostgresJobRepository,
    make_account: AccountFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Times come from the database: a wrong clock in this process cannot move run_at."""
    import time

    monkeypatch.setattr(time, "time", lambda: 0.0)
    account = await make_account()
    job_id = await submit_ok(jobs, account)
    job = await jobs.get_job(organisation_id=account.organisation_id, job_id=job_id)
    assert job is not None
    assert datetime.now(UTC) - job.run_at < timedelta(minutes=1)
