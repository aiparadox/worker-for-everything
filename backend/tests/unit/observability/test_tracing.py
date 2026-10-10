"""Trace ids and continuing a trace from a stored ``traceparent``."""

import re

import pytest
from opentelemetry import trace

from qfe.observability import continue_trace, current_trace_id, current_traceparent, setup_tracing

# The last field is the trace flags; the SDK sets bit 1 (random trace id) as well as bit 0.
TRACEPARENT = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
KNOWN = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
KNOWN_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
ALL_ZERO_VERSION_FF = "ff-" + "0" * 32 + "-" + "0" * 16 + "-00"


def test_no_trace_id_outside_a_span() -> None:
    assert current_trace_id() is None
    assert current_traceparent() is None


def test_a_span_has_a_real_trace_id_even_when_telemetry_is_off() -> None:
    with trace.get_tracer("t").start_as_current_span("work"):
        trace_id = current_trace_id()
        traceparent = current_traceparent()
    assert trace_id is not None
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
    assert traceparent is not None
    assert TRACEPARENT.match(traceparent)
    assert trace_id in traceparent


def test_continue_trace_keeps_the_trace_id() -> None:
    with continue_trace(KNOWN), trace.get_tracer("t").start_as_current_span("work"):
        assert current_trace_id() == KNOWN_TRACE_ID


@pytest.mark.parametrize("bad", [None, "", "garbage", "00-short-id-01", ALL_ZERO_VERSION_FF])
def test_a_missing_or_malformed_traceparent_starts_a_new_trace_and_is_not_an_error(
    bad: str | None,
) -> None:
    with continue_trace(bad), trace.get_tracer("t").start_as_current_span("work"):
        trace_id = current_trace_id()
    assert trace_id is not None
    assert trace_id != KNOWN_TRACE_ID


def test_telemetry_on_without_an_endpoint_is_refused() -> None:
    with pytest.raises(ValueError, match="OTLP endpoint"):
        setup_tracing("t", "on", None)
