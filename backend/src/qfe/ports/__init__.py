"""Interfaces only. Nothing here imports an adapter; adapters implement these."""

from qfe.ports.queue import (
    Consumer,
    Delivery,
    DeliveryCallback,
    PublishOutcome,
    QueueAdapter,
)
from qfe.ports.rate_limiter import (
    Decision,
    LimitClass,
    Rate,
    RateLimiter,
    RateLimiterUnavailable,
)
from qfe.ports.storage import (
    ObjectInfo,
    ObjectNotFound,
    PresignedUpload,
    StorageAdapter,
    StorageError,
    StorageUnavailable,
)
from qfe.ports.system import Clock, IdGenerator

__all__ = [
    "Clock",
    "Consumer",
    "Decision",
    "Delivery",
    "DeliveryCallback",
    "IdGenerator",
    "LimitClass",
    "ObjectInfo",
    "ObjectNotFound",
    "PresignedUpload",
    "PublishOutcome",
    "QueueAdapter",
    "Rate",
    "RateLimiter",
    "RateLimiterUnavailable",
    "StorageAdapter",
    "StorageError",
    "StorageUnavailable",
]
