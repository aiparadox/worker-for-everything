"""ASGI middleware: ``X-Trace-Id`` on every response, request metrics and one access log line.

It runs inside the OpenTelemetry middleware, which has already continued or started the trace
(a missing or malformed ``traceparent`` starts a new trace, it is never an error).
"""

import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qfe.observability.logging import get_logger
from qfe.observability.metrics import HTTP_DURATION, HTTP_REQUESTS
from qfe.observability.tracing import current_trace_id

TRACE_HEADER = "X-Trace-Id"
_UNMATCHED_ROUTE = "unmatched"  # one value for every 404, so unknown paths cannot add labels

_log = get_logger("qfe.api.access")


def route_template(scope: Scope) -> str:
    """The route's path pattern (for example ``/v1/jobs/{id}``), never the raw path."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else _UNMATCHED_ROUTE


def add_trace_header(message: Message) -> None:
    """Set ``X-Trace-Id`` on an ``http.response.start`` message."""
    trace_id = current_trace_id()
    if trace_id:
        MutableHeaders(scope=message)[TRACE_HEADER] = trace_id


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500

        async def send_with_trace_header(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                add_trace_header(message)
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_header)
        finally:
            elapsed = time.perf_counter() - started
            method = scope["method"]
            route = route_template(scope)
            HTTP_REQUESTS.labels(method, route, f"{status // 100}xx").inc()
            HTTP_DURATION.labels(method, route).observe(elapsed)
            _log.info(
                "request",
                method=method,
                route=route,
                status=status,
                duration_ms=round(elapsed * 1000, 1),
            )
