"""Job type definitions (docs/specs/FEAT-20261010-1212-job-type-registry.md)."""

import pytest
from pydantic import BaseModel

from qfe.domain import RetryPolicy
from qfe.job_types import InputModel, JobTypeDefinition, OutputModel
from qfe.job_types.echo import ECHO, ECHO_TIMEOUT_SECONDS, MAX_SLEEP_SECONDS


class In(InputModel):
    value: str


class Out(OutputModel):
    value: str


def make(**overrides: object) -> JobTypeDefinition:
    values: dict[str, object] = {
        "name": "sample.job",
        "version": "1",
        "input_schema": In,
        "output_schema": Out,
        "timeout_seconds": 60,
    }
    values.update(overrides)
    return JobTypeDefinition(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name", ["echo", "ocr.extract", "a", "web_scrape.page", "a.b.c", "x1.y2", "a" * 100]
)
def test_good_names(name: str) -> None:
    assert make(name=name).name == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Echo",
        "has space",
        "slash/name",
        "dash-name",
        ".leading",
        "trailing.",
        "double..dot",
        "1starts_with_digit",
        "a" * 101,
        "ünïcode",
        "queue*wild",
    ],
)
def test_bad_names_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="job type name"):
        make(name=name)


@pytest.mark.parametrize("timeout", [0, -1, -0.5])
def test_a_non_positive_timeout_is_refused(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        make(timeout_seconds=timeout)


@pytest.mark.parametrize("version", ["", "   "])
def test_an_empty_version_is_refused(version: str) -> None:
    with pytest.raises(ValueError, match="version"):
        make(version=version)


def test_an_input_schema_that_accepts_unknown_fields_is_refused() -> None:
    class Loose(BaseModel):
        value: str

    with pytest.raises(ValueError, match="unknown fields"):
        make(input_schema=Loose)


def test_a_definition_cannot_be_changed_after_it_is_made() -> None:
    definition = make()
    with pytest.raises(AttributeError):
        definition.name = "other"  # type: ignore[misc]


def test_a_type_without_a_policy_uses_the_default_and_one_with_its_own_keeps_it() -> None:
    default = RetryPolicy(max_attempts=4, delays_seconds=(10, 120, 600), jitter=0.2)
    own = RetryPolicy(max_attempts=2, delays_seconds=(5,), jitter=0.0)
    assert make().retry_policy_or(default) is default
    assert make(retry_policy=own).retry_policy_or(default) is own


def test_the_echo_definition() -> None:
    assert (ECHO.name, ECHO.version) == ("echo", "1")
    assert ECHO.retry_policy is None
    assert ECHO.timeout_seconds > MAX_SLEEP_SECONDS
    assert ECHO.timeout_seconds == ECHO_TIMEOUT_SECONDS
