"""JSON logs: shape, trace ids, bound ids, redaction (docs/ARCHITECTURE.md sections 12 and 16)."""

import json
import logging

import pytest
from opentelemetry import trace

from qfe.observability import (
    bind_log_context,
    clear_log_context,
    configure_logging,
    current_trace_id,
    get_logger,
)

TRACE_ID_LENGTH = 32
SPAN_ID_LENGTH = 16


@pytest.fixture(autouse=True)
def json_logging(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("unit-test")
    clear_log_context()
    capsys.readouterr()  # drop anything written while configuring


def lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_a_line_is_one_json_object_with_the_required_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_logger("test").info("hello", answer=42)
    (line,) = lines(capsys)
    assert line["event"] == "hello"
    assert line["level"] == "info"
    assert line["service"] == "unit-test"
    assert line["answer"] == 42
    assert str(line["timestamp"]).endswith("Z")


def test_trace_and_span_ids_appear_inside_a_span_and_not_outside(
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_logger("test").info("outside")
    with trace.get_tracer("test").start_as_current_span("work"):
        expected = current_trace_id()
        get_logger("test").info("inside")
    outside, inside = lines(capsys)
    assert "trace_id" not in outside
    assert inside["trace_id"] == expected
    assert len(str(inside["trace_id"])) == TRACE_ID_LENGTH
    assert len(str(inside["span_id"])) == SPAN_ID_LENGTH


def test_org_and_job_ids_can_be_bound_for_the_current_task(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bind_log_context(org_id="o1", job_id="j1")
    get_logger("test").info("with ids")
    clear_log_context()
    get_logger("test").info("without ids")
    with_ids, without_ids = lines(capsys)
    assert (with_ids["org_id"], with_ids["job_id"]) == ("o1", "j1")
    assert "org_id" not in without_ids


@pytest.mark.parametrize(
    "key", ["password", "api_key", "Authorization", "refresh_token", "client_secret", "cookie"]
)
def test_sensitive_values_are_replaced(capsys: pytest.CaptureFixture[str], key: str) -> None:
    get_logger("test").info("login", **{key: "hunter2-value"})
    out = capsys.readouterr().out
    assert "hunter2-value" not in out
    assert "[redacted]" in out


def test_sensitive_values_inside_nested_data_are_replaced(
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_logger("test").info("request", headers={"authorization": "Bearer abc123", "ok": "yes"})
    out = capsys.readouterr().out
    assert "abc123" not in out
    assert '"ok": "yes"' in out


def test_standard_library_and_library_loggers_use_the_same_format(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("uvicorn.error").warning("from a library")
    logging.getLogger("some.library").error("another one")
    first, second = lines(capsys)
    assert first["event"] == "from a library"
    assert first["level"] == "warning"
    assert second["service"] == "unit-test"


def test_an_exception_is_logged_as_text_in_the_same_json_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("test").exception("failed")
    (line,) = lines(capsys)
    assert "ValueError: boom" in str(line["exception"])


def test_the_server_access_log_is_silenced_because_our_middleware_writes_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET / HTTP/1.1" 200')
    assert lines(capsys) == []
