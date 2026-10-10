"""The FastAPI application: for now only the operational endpoints (docs/specs/...-1205-...).

``create_app`` knows nothing about settings or adapters; it receives the readiness checks and the
shutdown callbacks. ``qfe.api.main`` is the one place that wires real settings and adapters.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from qfe.observability.health import ReadinessCheck, run_checks
from qfe.observability.logging import get_logger
from qfe.observability.metrics import REGISTRY
from qfe.observability.middleware import TRACE_HEADER, ObservabilityMiddleware
from qfe.observability.tracing import current_trace_id

_log = get_logger(__name__)

ShutdownCallback = Callable[[], Awaitable[None]]


def create_app(
    readiness_checks: list[ReadinessCheck],
    shutdown_callbacks: list[ShutdownCallback] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        for callback in shutdown_callbacks or []:
            await callback()

    app = FastAPI(title="queue-for-everything", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """The process is running. Checks nothing else."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Dependencies are reachable. 503 only when a critical one (Postgres) is down."""
        report = await run_checks(readiness_checks)
        return JSONResponse(report.as_dict(), status_code=200 if report.ready else 503)

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        _log.exception("unhandled error", error_type=type(exc).__name__)
        response = JSONResponse(
            {"error": {"code": "internal_error", "message": "Internal server error"}},
            status_code=500,
        )
        # This handler runs outside the observability middleware, so it sets the header itself.
        trace_id = current_trace_id()
        if trace_id:
            response.headers[TRACE_HEADER] = trace_id
        return response

    app.add_middleware(ObservabilityMiddleware)
    # Outermost: continues or starts the trace before anything else runs.
    FastAPIInstrumentor.instrument_app(app)
    return app
