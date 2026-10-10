"""Retry or fail, and how long to wait before the next try.

One decision function serves both the worker (the handler failed) and maintenance (the lease
expired), so a job that crashes its worker is treated exactly like one that raises an error: a lost
lease counts as an attempt, and a job that crashes every worker fails after ``max_attempts``
(docs/ARCHITECTURE.md sections 10 and 11).

The delay is a *duration*, never a timestamp: SQL adds it to the database clock
(``run_at = now() + delay``, D24).
"""

from dataclasses import dataclass
from datetime import timedelta

from qfe.domain.job_state import JobEvent


@dataclass(frozen=True)
class RetryPolicy:
    """How a job type retries. ``max_attempts`` counts the first run plus the retries, so a policy
    with ``max_attempts = 4`` has 3 delays: one before each retry."""

    max_attempts: int
    delays_seconds: tuple[float, ...]
    jitter: float
    """A fraction: 0.2 spreads each delay by plus or minus 20%."""

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if len(self.delays_seconds) < self.max_attempts - 1:
            raise ValueError(
                f"max_attempts {self.max_attempts} needs {self.max_attempts - 1} retry delays, "
                f"but only {len(self.delays_seconds)} were given"
            )
        if any(delay <= 0 for delay in self.delays_seconds):
            raise ValueError("every retry delay must be positive")
        if not 0 <= self.jitter < 1:
            raise ValueError("jitter must be at least 0 and below 1")


def decide_after_failure(attempts: int, max_attempts: int, *, permanent: bool) -> JobEvent:
    """``RETRY`` or ``FAIL`` after a try failed.

    ``attempts`` is the number of tries used so far, including the one that just failed. A
    permanent error (bad input, unsupported file) never retries.
    """
    if permanent or attempts >= max_attempts:
        return JobEvent.FAIL
    return JobEvent.RETRY


def retry_delay(policy: RetryPolicy, failed_attempt: int, random_unit: float) -> timedelta:
    """How long to wait before the retry that follows try number ``failed_attempt``.

    ``random_unit`` is a number in [0, 1) supplied by the caller (the application passes
    ``random.random()``; tests pass fixed values), so the domain has no hidden randomness.
    """
    if not 1 <= failed_attempt <= policy.max_attempts - 1:
        last = policy.max_attempts - 1
        raise ValueError(f"attempt {failed_attempt} has no retry: valid values are 1 to {last}")
    if not 0 <= random_unit < 1:
        raise ValueError("random_unit must be at least 0 and below 1")
    base = policy.delays_seconds[failed_attempt - 1]
    factor = 1 + policy.jitter * (2 * random_unit - 1)
    return timedelta(milliseconds=round(base * factor * 1000))
