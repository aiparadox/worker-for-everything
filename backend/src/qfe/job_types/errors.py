"""Errors of the job type registry and the error a handler raises to fail a job at once."""

from dataclasses import dataclass


class PermanentError(Exception):
    """Raised by a handler for a failure that retrying cannot fix: bad input, an unsupported file.
    The job fails at once with no retries. Any other exception is retried until ``max_attempts``.

    ``code`` is what a client sees; ``message`` is for logs and may be filtered before a client
    sees it (findings.md F-26).
    """

    def __init__(self, message: str, code: str = "permanent_error") -> None:
        super().__init__(message)
        self.code = code


class UnknownJobType(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"unknown job type: {name}")
        self.name = name


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a submitted payload. Never contains the submitted value: a payload may
    hold the text of sensitive documents, and logs and error bodies must not repeat it."""

    loc: tuple[str | int, ...]
    message: str
    code: str


class InvalidPayload(Exception):
    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"invalid payload: {len(problems)} problem(s)")
        self.problems = problems
