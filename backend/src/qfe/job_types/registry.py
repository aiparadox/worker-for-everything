"""The registry of job types, built explicitly (nothing is discovered by magic), and payload
validation. ``default_registry()`` is the one place that lists the types.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from qfe.job_types.definition import JobTypeDefinition
from qfe.job_types.echo import ECHO
from qfe.job_types.errors import InvalidPayload, Problem, UnknownJobType
from qfe.job_types.file_ref import FileRef, find_file_refs

# Pydantic error types whose message never repeats the submitted value. Every other type gets a
# generic message, because for some (a malformed UUID, for example) pydantic's text quotes part of
# the input, and a payload may hold sensitive text.
_SAFE_MESSAGE_TYPES = frozenset(
    {
        "missing",
        "extra_forbidden",
        "string_type",
        "string_too_short",
        "string_too_long",
        "int_type",
        "int_parsing",
        "float_type",
        "float_parsing",
        "bool_type",
        "bool_parsing",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "literal_error",
        "dict_type",
        "list_type",
        "model_type",
        "too_short",
        "too_long",
    }
)
_GENERIC_MESSAGE = "Invalid value"


@dataclass(frozen=True)
class ValidatedPayload:
    job_type: str
    model: BaseModel
    payload: dict[str, Any]
    """The payload as plain JSON (file ids as strings): what is stored in ``jobs.payload``."""
    file_ids: tuple[FileRef, ...]
    """Every file id in the payload, each once, for the caller to check."""


class JobTypeRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, JobTypeDefinition] = {}

    def register(self, definition: JobTypeDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"job type {definition.name!r} is registered twice")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> JobTypeDefinition:
        try:
            return self._definitions[name]
        except KeyError:
            raise UnknownJobType(name) from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def definitions(self) -> tuple[JobTypeDefinition, ...]:
        return tuple(self._definitions[name] for name in self.names())

    def require(self, names: Iterable[str]) -> None:
        """Raise ``UnknownJobType`` for the first name that is not registered (used at startup)."""
        for name in names:
            self.get(name)

    def expand(self, wanted: Sequence[str] | Literal["*"]) -> tuple[str, ...]:
        """The job types a worker serves: ``*`` means every registered type. Unknown names raise."""
        if wanted == "*":
            return self.names()
        names = tuple(wanted)
        self.require(names)
        return names

    def validate_payload(self, name: str, payload: object) -> ValidatedPayload:
        """Check ``payload`` against the input schema of type ``name``.

        Raises ``UnknownJobType`` or ``InvalidPayload``. The problems never contain the submitted
        value. The size cap on the payload is checked by the caller.
        """
        definition = self.get(name)
        if not isinstance(payload, dict):
            raise InvalidPayload([Problem((), "The payload must be a JSON object", "model_type")])
        try:
            model = definition.input_schema.model_validate(payload)
        except ValidationError as error:
            raise InvalidPayload(_problems(error)) from None
        return ValidatedPayload(
            job_type=name,
            model=model,
            payload=model.model_dump(mode="json"),
            file_ids=find_file_refs(model),
        )


def _problems(error: ValidationError) -> list[Problem]:
    problems: list[Problem] = []
    for item in error.errors(include_input=False, include_url=False, include_context=False):
        error_type = item["type"]
        message = item["msg"] if error_type in _SAFE_MESSAGE_TYPES else _GENERIC_MESSAGE
        problems.append(Problem(tuple(item["loc"]), message, error_type))
    return problems


def default_registry() -> JobTypeRegistry:
    """Every job type the system can run. Add new types here, explicitly."""
    registry = JobTypeRegistry()
    registry.register(ECHO)
    return registry
