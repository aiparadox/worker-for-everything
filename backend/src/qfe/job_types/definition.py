"""The light definition of one job type.

The API, the relay and the worker all import this, so it must stay light: no OCR or AI libraries.
The code that does the work (a handler) lives elsewhere and only workers load it
(docs/ARCHITECTURE.md section 6).
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel

from qfe.domain import RetryPolicy

# Lower-case dotted words such as "echo" or "ocr.extract". The name is also a RabbitMQ queue name
# and a metric label, so only safe characters are allowed.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
MAX_NAME_LENGTH = 100


@dataclass(frozen=True)
class JobTypeDefinition:
    name: str
    """Becomes ``jobs.type``, the outbox routing key and the queue name."""
    version: str
    """Copied to ``jobs.type_version`` when a job is submitted."""
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    timeout_seconds: float
    """Stored and shown here. What enforces it is the worker's job."""
    retry_policy: RetryPolicy | None = None
    """``None`` means: use the default policy from configuration."""

    def __post_init__(self) -> None:
        if not 1 <= len(self.name) <= MAX_NAME_LENGTH or not NAME_PATTERN.match(self.name):
            raise ValueError(
                f"job type name {self.name!r} must be lower-case dotted words such as 'ocr.extract'"
            )
        if not self.version.strip():
            raise ValueError(f"job type {self.name}: the version must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError(f"job type {self.name}: the timeout must be positive")
        if self.input_schema.model_config.get("extra") != "forbid":
            raise ValueError(
                f"job type {self.name}: the input schema must refuse unknown fields "
                "(derive it from qfe.job_types.InputModel)"
            )

    def retry_policy_or(self, default: RetryPolicy) -> RetryPolicy:
        """This type's own retry policy, or ``default`` when it defines none."""
        return self.retry_policy if self.retry_policy is not None else default
