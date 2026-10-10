"""Prometheus metrics.

Naming rule: every metric starts with ``qfe_``. Never use ``org_id``, ``job_id`` or a user id as a
label (too many values); ``job_type`` is a safe label. Domain metrics (queue depth, failed jobs,
sweep re-queues, stuck outbox rows) are added by the tasks that own them.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "qfe_http_requests_total",
    "HTTP requests handled, by method, route template and status class.",
    ["method", "route", "status_class"],
    registry=REGISTRY,
)

HTTP_DURATION = Histogram(
    "qfe_http_request_duration_seconds",
    "HTTP request duration in seconds, by method and route template.",
    ["method", "route"],
    registry=REGISTRY,
)


def start_metrics_server(port: int) -> None:
    """Serve ``/metrics`` on a small separate port for processes that are not web servers
    (worker, relay, maintenance)."""
    start_http_server(port, registry=REGISTRY)
