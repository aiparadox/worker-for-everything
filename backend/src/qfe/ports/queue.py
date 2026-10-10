"""The queue port: how jobs are announced to workers.

The first implementation is RabbitMQ with one durable queue per job type (D5, D28). Another
broker must pass the same contract suite (tests/contract/queue). The contract the design needs:

- publishing reports one of four outcomes, so an unroutable message is never mistaken for success;
- a message waits in its queue until a consumer for that type exists;
- an unacknowledged message is delivered again;
- a consumer holds at most one delivered, unacknowledged message per queue.

``consume`` is **provisional**: its exact shape depends on the worker design (handler execution and
delivery settings, ISS-20261010-1155) and may change in the worker spec.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PublishOutcome(StrEnum):
    CONFIRMED = "confirmed"
    """The broker confirmed the message and did not return it."""
    RETURNED = "returned"
    """The broker could not route it, for example because no queue exists for the type."""
    REJECTED = "rejected"
    """The broker refused the message."""
    UNKNOWN = "unknown"
    """The confirmation was lost: the message may or may not have been published, and publishing
    again can create a duplicate (which the at-least-once rule tolerates)."""


@dataclass(frozen=True)
class Delivery:
    """A message handed to a consumer. ``handle`` belongs to the adapter; pass the whole object
    back to ``ack`` or ``nack_requeue``."""

    routing_key: str
    body: bytes
    headers: Mapping[str, str]
    redelivered: bool
    handle: object


DeliveryCallback = Callable[[Delivery], Awaitable[None]]


class Consumer(Protocol):
    """A running subscription to the queues of some job types."""

    async def pause(self) -> None:
        """Stop receiving new messages (the worker has no free concurrency). Messages already
        delivered stay with the consumer until acknowledged."""
        ...

    async def resume(self) -> None:
        """Start receiving messages again."""
        ...

    async def stop(self) -> None:
        """Stop for good. Delivered messages that were not acknowledged go back to their queue."""
        ...


class QueueAdapter(Protocol):
    async def declare_queue(self, job_type: str) -> None:
        """Create the durable queue for ``job_type`` if it does not exist. Safe to repeat."""
        ...

    async def publish(
        self, routing_key: str, body: bytes, headers: Mapping[str, str]
    ) -> PublishOutcome: ...

    async def consume(self, job_types: Sequence[str], on_delivery: DeliveryCallback) -> Consumer:
        """Subscribe to the queues of ``job_types`` only. Provisional, see the module text."""
        ...

    async def ack(self, delivery: Delivery) -> None:
        """Tell the broker to forget the message."""
        ...

    async def nack_requeue(self, delivery: Delivery) -> None:
        """Hand the message back so another consumer can take it."""
        ...

    async def close(self) -> None: ...
