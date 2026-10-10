"""Logging, tracing, metrics and health checks shared by every process."""

from qfe.observability.health import (
    CheckResult,
    ReadinessCheck,
    ReadinessReport,
    run_checks,
)
from qfe.observability.logging import (
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
)
from qfe.observability.metrics import REGISTRY, start_metrics_server
from qfe.observability.tracing import (
    continue_trace,
    current_trace_id,
    current_traceparent,
    setup_tracing,
)

__all__ = [
    "REGISTRY",
    "CheckResult",
    "ReadinessCheck",
    "ReadinessReport",
    "bind_log_context",
    "clear_log_context",
    "configure_logging",
    "continue_trace",
    "current_trace_id",
    "current_traceparent",
    "get_logger",
    "run_checks",
    "setup_tracing",
    "start_metrics_server",
]
