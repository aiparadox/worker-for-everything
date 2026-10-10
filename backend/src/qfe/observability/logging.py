"""JSON logging with the trace id on every line inside a trace.

One JSON object per line on standard output. Fields: ``timestamp`` (UTC), ``level``, ``event``,
``service``, ``trace_id`` and ``span_id`` (while a span is active), and ``org_id`` / ``job_id``
when code has bound them. The standard library's loggers (uvicorn, SQLAlchemy and so on) go
through the same format, so the output has one shape (docs/ARCHITECTURE.md section 12).
Secrets are replaced before anything is written (section 16).
"""

import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from opentelemetry import trace
from structlog.typing import EventDict, Processor, WrappedLogger

_SENSITIVE_KEY = re.compile(
    r"password|secret|token|authorization|api[_-]?key|cookie", re.IGNORECASE
)
REDACTED = "[redacted]"


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with the content of sensitive keys replaced."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    return value


def _redact_processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    return {
        key: REDACTED if _SENSITIVE_KEY.search(key) else redact(value)
        for key, value in event_dict.items()
    }


def _add_trace_ids(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


def _add_service(service_name: str) -> Processor:
    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        event_dict["service"] = service_name
        return event_dict

    return processor


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever ``sys.stdout`` is at the moment of writing, like the standard library's
    own stderr handler. A handler bound to one stream object keeps writing to a stale stream when
    something (a test runner, a process manager) swaps ``sys.stdout``."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> Any:
        return sys.stdout


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Send all logging, ours and the libraries', to standard output as JSON."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        _add_service(service_name),
        _add_trace_ids,
        structlog.processors.format_exc_info,
        _redact_processor,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = _StdoutHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn installs its own handlers; hand its records to the root handler instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        library_logger = logging.getLogger(name)
        library_logger.handlers = []
        library_logger.propagate = True
    # Our middleware writes the access line (with the trace id), so uvicorn's own is silenced.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger


def bind_log_context(**values: str) -> None:
    """Add ``org_id`` / ``job_id`` (or other ids) to every log line of the current task."""
    structlog.contextvars.bind_contextvars(**values)


def clear_log_context() -> None:
    structlog.contextvars.clear_contextvars()
