"""The job state machine: one transition table.

Every part that changes a job's status asks this table; nothing else decides a status change
(docs/ARCHITECTURE.md section 5):

    queued ---CLAIM---> running ---SUCCEED---> succeeded
    retrying -CLAIM---> running ---RETRY-----> retrying
                                 ---FAIL------> failed

A retry never returns to ``queued``. ``cancelled`` is a valid stored status (the database allows
it from day one) but no event leads to it yet: cancel is a Phase 2 feature with its own spec.
"""

from enum import StrEnum
from types import MappingProxyType


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobEvent(StrEnum):
    CLAIM = "claim"
    """A worker takes the job and starts a try."""
    SUCCEED = "succeed"
    """The handler finished."""
    RETRY = "retry"
    """The try failed (handler error or lost lease) and tries are left."""
    FAIL = "fail"
    """The try failed for good: a permanent error, or no tries left."""


# Statuses counted by the active-jobs cap (a live job is queued, waiting to retry, or running).
LIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RETRYING, JobStatus.RUNNING})
# Statuses a job never leaves. Only these may be purged.
FINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})

TRANSITIONS = MappingProxyType(
    {
        (JobStatus.QUEUED, JobEvent.CLAIM): JobStatus.RUNNING,
        (JobStatus.RETRYING, JobEvent.CLAIM): JobStatus.RUNNING,
        (JobStatus.RUNNING, JobEvent.SUCCEED): JobStatus.SUCCEEDED,
        (JobStatus.RUNNING, JobEvent.RETRY): JobStatus.RETRYING,
        (JobStatus.RUNNING, JobEvent.FAIL): JobStatus.FAILED,
    }
)


class InvalidTransition(Exception):
    def __init__(self, status: JobStatus, event: JobEvent) -> None:
        super().__init__(f"a {status.value} job cannot take the event {event.value}")
        self.status = status
        self.event = event


def next_status(status: JobStatus, event: JobEvent) -> JobStatus:
    """The status after ``event``, or ``InvalidTransition`` if the table has no such move."""
    try:
        return TRANSITIONS[(status, event)]
    except KeyError:
        raise InvalidTransition(status, event) from None


def source_statuses(event: JobEvent) -> frozenset[JobStatus]:
    """The statuses a job may be in when ``event`` happens. A database operation uses this in its
    ``WHERE status IN (...)`` so that SQL and the table cannot disagree."""
    return frozenset(status for (status, e) in TRANSITIONS if e is event)
