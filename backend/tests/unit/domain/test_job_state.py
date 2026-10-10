"""The job state machine (docs/specs/FEAT-20261010-1210-domain.md)."""

import itertools

import pytest

from qfe.adapters.postgres.tables import ACTIVE_JOB_STATUSES, JOB_STATUSES
from qfe.domain import (
    FINAL_STATUSES,
    LIVE_STATUSES,
    TRANSITIONS,
    InvalidTransition,
    JobEvent,
    JobStatus,
    next_status,
    source_statuses,
)

S, E = JobStatus, JobEvent

# The state diagram of docs/ARCHITECTURE.md section 5, written out. Anything else is illegal.
LEGAL = {
    (S.QUEUED, E.CLAIM): S.RUNNING,
    (S.RETRYING, E.CLAIM): S.RUNNING,
    (S.RUNNING, E.SUCCEED): S.SUCCEEDED,
    (S.RUNNING, E.RETRY): S.RETRYING,
    (S.RUNNING, E.FAIL): S.FAILED,
}
ALL_PAIRS = list(itertools.product(JobStatus, JobEvent))


@pytest.mark.parametrize(("status", "event"), ALL_PAIRS)
def test_every_pair_is_either_the_documented_move_or_refused(
    status: JobStatus, event: JobEvent
) -> None:
    if (status, event) in LEGAL:
        assert next_status(status, event) is LEGAL[(status, event)]
    else:
        with pytest.raises(InvalidTransition) as refusal:
            next_status(status, event)
        assert status.value in str(refusal.value)
        assert event.value in str(refusal.value)


def test_the_table_holds_exactly_the_documented_moves() -> None:
    assert dict(TRANSITIONS) == LEGAL


@pytest.mark.parametrize("final", sorted(FINAL_STATUSES))
@pytest.mark.parametrize("event", list(JobEvent))
def test_no_event_leaves_a_final_status(final: JobStatus, event: JobEvent) -> None:
    with pytest.raises(InvalidTransition):
        next_status(final, event)


def test_nothing_leads_back_to_queued_and_nothing_leads_to_cancelled_yet() -> None:
    targets = set(TRANSITIONS.values())
    assert JobStatus.QUEUED not in targets
    assert JobStatus.CANCELLED not in targets  # cancel is Phase 2


def test_the_transition_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        TRANSITIONS[(JobStatus.QUEUED, JobEvent.FAIL)] = JobStatus.FAILED  # type: ignore[index]


def test_the_statuses_equal_the_database_check() -> None:
    assert {status.value for status in JobStatus} == set(JOB_STATUSES)


def test_live_statuses_equal_the_statuses_of_the_active_jobs_index() -> None:
    assert {status.value for status in LIVE_STATUSES} == set(ACTIVE_JOB_STATUSES)


def test_every_status_is_live_or_final_and_not_both() -> None:
    assert set(JobStatus) == LIVE_STATUSES | FINAL_STATUSES
    assert set() == LIVE_STATUSES & FINAL_STATUSES


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (E.CLAIM, {S.QUEUED, S.RETRYING}),
        (E.SUCCEED, {S.RUNNING}),
        (E.RETRY, {S.RUNNING}),
        (E.FAIL, {S.RUNNING}),
    ],
)
def test_source_statuses_for_the_where_clause_of_a_database_operation(
    event: JobEvent, expected: set[JobStatus]
) -> None:
    assert source_statuses(event) == expected
