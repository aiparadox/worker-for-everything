"""The registry and payload validation (docs/specs/FEAT-20261010-1212-job-type-registry.md)."""

import importlib
import pkgutil
import subprocess
import sys
import uuid
from typing import Any

import pytest
from pydantic import Field

import qfe.job_types
from qfe.job_types import (
    FileRef,
    InputModel,
    InvalidPayload,
    JobTypeDefinition,
    JobTypeRegistry,
    OutputModel,
    UnknownJobType,
    default_registry,
)

DOCUMENT_TEXT = "TOP-SECRET-DOCUMENT-TEXT-12345"


class Inner(InputModel):
    attachments: list[FileRef]


class DocsIn(InputModel):
    document: FileRef
    extra: list[FileRef] = Field(default_factory=list)
    optional: FileRef | None = None
    inner: Inner | None = None
    title: str = Field(default="", max_length=20)
    pages: int = Field(default=1, ge=1, le=10)


class DocsOut(OutputModel):
    ok: bool


DOCS = JobTypeDefinition(
    name="docs.read",
    version="2",
    input_schema=DocsIn,
    output_schema=DocsOut,
    timeout_seconds=30,
)


@pytest.fixture
def registry() -> JobTypeRegistry:
    registry = default_registry()
    registry.register(DOCS)
    return registry


def ids(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]


# --- the registry itself -----------------------------------------------------------------------


def test_the_default_registry_has_echo() -> None:
    assert default_registry().names() == ("echo",)


def test_register_and_get(registry: JobTypeRegistry) -> None:
    assert registry.get("docs.read") is DOCS
    assert registry.names() == ("docs.read", "echo")
    assert [d.name for d in registry.definitions()] == ["docs.read", "echo"]


def test_registering_the_same_name_twice_is_refused(registry: JobTypeRegistry) -> None:
    with pytest.raises(ValueError, match="registered twice"):
        registry.register(DOCS)


def test_an_unknown_type_raises(registry: JobTypeRegistry) -> None:
    with pytest.raises(UnknownJobType) as error:
        registry.get("nope")
    assert error.value.name == "nope"


def test_require_names_the_first_missing_type(registry: JobTypeRegistry) -> None:
    registry.require(["echo", "docs.read"])
    with pytest.raises(UnknownJobType, match=r"ocr\.extract"):
        registry.require(["echo", "ocr.extract"])


def test_a_star_expands_to_every_type_and_a_list_is_checked(registry: JobTypeRegistry) -> None:
    assert registry.expand("*") == ("docs.read", "echo")
    assert registry.expand(["echo"]) == ("echo",)
    with pytest.raises(UnknownJobType):
        registry.expand(["echo", "missing"])


def test_every_definition_in_the_package_is_registered() -> None:
    """A new type that is written but not listed in default_registry() would never run."""
    defined: set[str] = set()
    for module_info in pkgutil.iter_modules(qfe.job_types.__path__):
        module = importlib.import_module(f"qfe.job_types.{module_info.name}")
        defined.update(
            value.name for value in vars(module).values() if isinstance(value, JobTypeDefinition)
        )
    assert defined == set(default_registry().names())


def test_importing_the_package_stays_light() -> None:
    """The API and relay import job types; they must not pull in handlers, adapters or the heavy
    libraries (checked in a fresh process, so earlier imports cannot hide a problem)."""
    code = (
        "import sys, qfe.job_types\n"
        "heavy = ['qfe.handlers', 'qfe.adapters', 'boto3', 'aio_pika', 'sqlalchemy', 'redis', "
        "'asyncpg', 'httpx2', 'fastapi']\n"
        "loaded = [name for name in heavy if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed code, no user input
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


# --- validate_payload --------------------------------------------------------------------------


def test_a_valid_echo_payload_round_trips() -> None:
    result = default_registry().validate_payload("echo", {"message": "hi"})
    assert result.job_type == "echo"
    assert result.payload == {
        "message": "hi",
        "fail_attempts": 0,
        "permanent_error": False,
        "sleep_seconds": 0.0,
    }
    assert result.file_ids == ()


def test_file_ids_are_collected_from_every_place(registry: JobTypeRegistry) -> None:
    a, b, c, d, e = ids(5)
    result = registry.validate_payload(
        "docs.read",
        {
            "document": a,
            "extra": [b, c],
            "optional": d,
            "inner": {"attachments": [e, a]},
        },
    )
    assert {str(ref) for ref in result.file_ids} == {a, b, c, d, e}
    assert len(result.file_ids) == 5  # duplicates once
    assert all(
        isinstance(value, str) for value in (result.payload["document"], *result.payload["extra"])
    )


def test_the_stored_payload_is_plain_json(registry: JobTypeRegistry) -> None:
    import json

    (doc,) = ids(1)
    result = registry.validate_payload("docs.read", {"document": doc})
    assert json.loads(json.dumps(result.payload)) == result.payload


def problems_of(registry: JobTypeRegistry, name: str, payload: Any) -> list[tuple[Any, str]]:
    with pytest.raises(InvalidPayload) as error:
        registry.validate_payload(name, payload)
    return [(problem.loc, problem.code) for problem in error.value.problems]


def test_a_missing_field_is_reported_with_its_path(registry: JobTypeRegistry) -> None:
    assert problems_of(registry, "docs.read", {}) == [(("document",), "missing")]


def test_an_unknown_field_is_reported(registry: JobTypeRegistry) -> None:
    (doc,) = ids(1)
    found = problems_of(registry, "docs.read", {"document": doc, "surprise": 1})
    assert found == [(("surprise",), "extra_forbidden")]


def test_a_wrong_type_and_a_range_error_are_reported(registry: JobTypeRegistry) -> None:
    (doc,) = ids(1)
    found = problems_of(registry, "docs.read", {"document": doc, "pages": 99, "title": "x" * 40})
    assert {item[0] for item in found} == {("pages",), ("title",)}


def test_a_nested_problem_has_a_full_path(registry: JobTypeRegistry) -> None:
    (doc,) = ids(1)
    found = problems_of(registry, "docs.read", {"document": doc, "inner": {"attachments": ["bad"]}})
    assert found[0][0][:3] == ("inner", "attachments", 0)


@pytest.mark.parametrize("payload", [None, [], "text", 5, [{"message": "x"}]])
def test_a_payload_that_is_not_an_object_is_refused(payload: Any) -> None:
    registry = default_registry()
    assert problems_of(registry, "echo", payload) == [((), "model_type")]


def test_an_unknown_type_is_reported_before_the_payload_is_looked_at() -> None:
    with pytest.raises(UnknownJobType):
        default_registry().validate_payload("nope", {"anything": 1})


@pytest.mark.parametrize(
    ("payload_for", "field"),
    [
        (lambda s: {"document": s}, "document"),  # a malformed UUID: pydantic quotes characters
        (lambda s: {"document": ids(1)[0], "pages": s}, "pages"),  # not an integer
        (lambda s: {"document": ids(1)[0], "title": [s]}, "title"),  # wrong type
        (lambda s: {"document": ids(1)[0], s: 1}, "extra key"),  # unknown key name
    ],
)
def test_error_details_never_repeat_the_submitted_value(
    registry: JobTypeRegistry, payload_for: Any, field: str
) -> None:
    with pytest.raises(InvalidPayload) as error:
        registry.validate_payload("docs.read", payload_for(DOCUMENT_TEXT))
    details = repr([(p.loc, p.message, p.code) for p in error.value.problems]) + str(error.value)
    if field == "extra key":
        # The key name is the client's own field name, not content; it may appear in the path.
        assert DOCUMENT_TEXT not in "".join(p.message for p in error.value.problems)
    else:
        assert DOCUMENT_TEXT not in details
        assert "TOP-SECRET" not in details
        assert "12345" not in details


def test_an_over_long_message_is_refused_by_echo() -> None:
    found = problems_of(default_registry(), "echo", {"message": "x" * 10_001})
    assert found == [(("message",), "string_too_long")]


def test_echo_refuses_negative_failures_and_huge_sleeps() -> None:
    found = problems_of(
        default_registry(), "echo", {"message": "m", "fail_attempts": -1, "sleep_seconds": 99999}
    )
    assert {item[0] for item in found} == {("fail_attempts",), ("sleep_seconds",)}
