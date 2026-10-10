"""Tracing: always real trace ids, exported only when telemetry is on.

A tracer provider is always installed, so every request and every log line has a real trace id
even with ``QFE_TELEMETRY=off``; the OTLP exporter is added only when telemetry is on. "Off" is an
explicit setting and is logged once (docs/specs/FEAT-20261010-1205-observability-skeleton.md).

Helpers for the relay and worker: ``current_traceparent`` gives a W3C ``traceparent`` string to
store on a job or put in a message header, and ``continue_trace`` continues a trace from one.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from qfe.observability.logging import get_logger

_propagator = TraceContextTextMapPropagator()


def setup_tracing(
    service_name: str, telemetry: Literal["on", "off"], otlp_endpoint: str | None
) -> TracerProvider:
    """Install the tracer provider for this process and return it."""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    log = get_logger(__name__)
    if telemetry == "on":
        if not otlp_endpoint:
            raise ValueError("an OTLP endpoint is required when telemetry is on")
        exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        log.info("telemetry enabled", otlp_endpoint=otlp_endpoint)
    else:
        log.warning("telemetry disabled by configuration (QFE_TELEMETRY=off)")
    trace.set_tracer_provider(provider)
    return provider


def current_trace_id() -> str | None:
    """The 32-character trace id of the current span, or None outside a trace."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def current_traceparent() -> str | None:
    """The current span as a W3C ``traceparent`` string, or None outside a trace."""
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


@contextmanager
def continue_trace(traceparent: str | None) -> Iterator[None]:
    """Make spans started inside this block part of the trace in ``traceparent``.

    A missing or malformed value starts a new trace; it is never an error.
    """
    context = _propagator.extract({"traceparent": traceparent} if traceparent else {})
    token = otel_context.attach(context)
    try:
        yield
    finally:
        otel_context.detach(token)
