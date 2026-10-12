"""The ``echo`` job type: the simplest real job, used by tests and examples.

Besides the message it carries three test controls so the failure and retry flows can be exercised
end to end with a real job: ``fail_attempts`` (fail with a retryable error on the first N tries),
``permanent_error`` (fail at once with a ``PermanentError``) and ``sleep_seconds`` (wait, for lease
and heartbeat tests). This is only the light definition; the handler comes with the worker.
"""

from pydantic import Field

from qfe.job_types.base import InputModel, OutputModel
from qfe.job_types.definition import JobTypeDefinition

MAX_MESSAGE_LENGTH = 10_000
MAX_FAIL_ATTEMPTS = 100
MAX_SLEEP_SECONDS = 3600
# Longer than the longest sleep, so the time limit never cuts a legitimate echo job short.
ECHO_TIMEOUT_SECONDS = MAX_SLEEP_SECONDS + 300


class EchoInput(InputModel):
    message: str = Field(max_length=MAX_MESSAGE_LENGTH)
    fail_attempts: int = Field(default=0, ge=0, le=MAX_FAIL_ATTEMPTS)
    permanent_error: bool = False
    sleep_seconds: float = Field(default=0, ge=0, le=MAX_SLEEP_SECONDS)


class EchoOutput(OutputModel):
    message: str
    attempt: int
    """The number of the attempt that produced this result."""


ECHO = JobTypeDefinition(
    name="echo",
    version="1",
    input_schema=EchoInput,
    output_schema=EchoOutput,
    timeout_seconds=ECHO_TIMEOUT_SECONDS,
)
