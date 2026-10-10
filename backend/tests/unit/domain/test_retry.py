"""Retry or fail, and the retry delay (docs/specs/FEAT-20261010-1210-domain.md)."""

from datetime import timedelta

import pytest

from qfe.domain import (
    InvalidTransition,
    JobEvent,
    JobStatus,
    RetryPolicy,
    decide_after_failure,
    next_status,
    retry_delay,
)

PLAN = RetryPolicy(max_attempts=4, delays_seconds=(10, 120, 600), jitter=0.2)
JUST_BELOW_ONE = 0.999999


# --- RetryPolicy ----------------------------------------------------------------------------


def test_the_plan_is_valid() -> None:
    assert PLAN.max_attempts == 4
    assert PLAN.delays_seconds == (10, 120, 600)


@pytest.mark.parametrize(
    ("max_attempts", "delays", "jitter", "message"),
    [
        (0, (), 0.2, "at least 1"),
        (-1, (), 0.2, "at least 1"),
        (4, (10, 120), 0.2, "needs 3 retry delays"),
        (2, (), 0.2, "needs 1 retry delays"),
        (3, (10, 0), 0.2, "positive"),
        (3, (10, -5), 0.2, "positive"),
        (3, (10, 20), -0.1, "jitter"),
        (3, (10, 20), 1.0, "jitter"),
        (3, (10, 20), 1.5, "jitter"),
    ],
)
def test_a_bad_policy_is_refused_when_it_is_built(
    max_attempts: int, delays: tuple[float, ...], jitter: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        RetryPolicy(max_attempts, delays, jitter)


def test_one_attempt_means_no_retries_and_needs_no_delays() -> None:
    policy = RetryPolicy(max_attempts=1, delays_seconds=(), jitter=0.0)
    assert decide_after_failure(1, policy.max_attempts, permanent=False) is JobEvent.FAIL


def test_extra_delays_are_allowed_and_unused() -> None:
    policy = RetryPolicy(max_attempts=2, delays_seconds=(5, 50, 500), jitter=0.0)
    assert retry_delay(policy, 1, 0.5) == timedelta(seconds=5)


# --- decide_after_failure --------------------------------------------------------------------


@pytest.mark.parametrize("max_attempts", [1, 2, 3, 4, 10])
@pytest.mark.parametrize("permanent", [False, True])
def test_the_decision_over_a_grid_of_attempts(max_attempts: int, permanent: bool) -> None:
    for attempts in range(1, max_attempts + 1):
        expected = JobEvent.FAIL if permanent or attempts >= max_attempts else JobEvent.RETRY
        assert decide_after_failure(attempts, max_attempts, permanent=permanent) is expected


@pytest.mark.parametrize("max_attempts", [1, 2, 3, 4, 7])
def test_a_job_that_always_fails_runs_exactly_max_attempts_times(max_attempts: int) -> None:
    """The crash-loop guarantee: whether the cause is an error or a lost lease, the job is tried
    ``max_attempts`` times, retried ``max_attempts - 1`` times, and then fails."""
    status, attempts, retries = JobStatus.QUEUED, 0, 0
    while True:
        status = next_status(status, JobEvent.CLAIM)
        attempts += 1
        event = decide_after_failure(attempts, max_attempts, permanent=False)
        status = next_status(status, event)
        if event is JobEvent.FAIL:
            break
        retries += 1
    assert status is JobStatus.FAILED
    assert (attempts, retries) == (max_attempts, max_attempts - 1)


def test_a_permanent_error_fails_at_once_even_on_the_first_attempt() -> None:
    assert decide_after_failure(1, 4, permanent=True) is JobEvent.FAIL


def test_a_failed_job_cannot_be_retried_by_mistake() -> None:
    status = next_status(next_status(JobStatus.QUEUED, JobEvent.CLAIM), JobEvent.FAIL)
    with pytest.raises(InvalidTransition):
        next_status(status, JobEvent.RETRY)


# --- retry_delay -----------------------------------------------------------------------------


@pytest.mark.parametrize(("failed_attempt", "base"), [(1, 10), (2, 120), (3, 600)])
def test_the_base_follows_the_schedule_and_jitter_spreads_it_by_20_percent(
    failed_attempt: int, base: float
) -> None:
    assert retry_delay(PLAN, failed_attempt, 0.0) == timedelta(seconds=base * 0.8)
    assert retry_delay(PLAN, failed_attempt, 0.5) == timedelta(seconds=base)
    high = retry_delay(PLAN, failed_attempt, JUST_BELOW_ONE)
    assert timedelta(seconds=base) < high < timedelta(seconds=base * 1.2 + 0.001)


def test_no_jitter_gives_exactly_the_base() -> None:
    policy = RetryPolicy(max_attempts=3, delays_seconds=(7, 70), jitter=0.0)
    for unit in (0.0, 0.3, 0.9):
        assert retry_delay(policy, 1, unit) == timedelta(seconds=7)
        assert retry_delay(policy, 2, unit) == timedelta(seconds=70)


def test_the_delay_is_always_positive_and_within_the_jitter_band() -> None:
    policy = RetryPolicy(max_attempts=2, delays_seconds=(1,), jitter=0.9)
    for step in range(1000):
        delay = retry_delay(policy, 1, step / 1000)
        assert timedelta(0) < delay <= timedelta(seconds=1.9)


def test_the_delay_is_rounded_to_milliseconds() -> None:
    policy = RetryPolicy(max_attempts=2, delays_seconds=(1,), jitter=0.3333)
    assert retry_delay(policy, 1, 0.123456).microseconds % 1000 == 0


@pytest.mark.parametrize("failed_attempt", [0, -1, 4, 5])
def test_an_attempt_with_no_retry_is_refused(failed_attempt: int) -> None:
    with pytest.raises(ValueError, match="has no retry"):
        retry_delay(PLAN, failed_attempt, 0.5)


@pytest.mark.parametrize("unit", [-0.1, 1.0, 2.0])
def test_a_random_unit_outside_zero_to_one_is_refused(unit: float) -> None:
    with pytest.raises(ValueError, match="random_unit"):
        retry_delay(PLAN, 1, unit)
