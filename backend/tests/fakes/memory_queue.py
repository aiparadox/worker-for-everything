"""An in-memory QueueAdapter that behaves like the broker contract in qfe.ports.queue.

Fake-only controls (not part of the port): ``force_outcome`` makes the next publishes report
REJECTED or UNKNOWN, which a real broker cannot be told to do.
"""

import asyncio
import itertools
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from qfe.ports import Delivery, DeliveryCallback, PublishOutcome


@dataclass
class _Message:
    routing_key: str
    body: bytes
    headers: Mapping[str, str]
    redelivered: bool = False


@dataclass
class _Held:
    message: _Message
    consumer: "_MemoryConsumer"


@dataclass
class _MemoryConsumer:
    queue: "InMemoryQueue"
    job_types: tuple[str, ...]
    on_delivery: DeliveryCallback
    paused: bool = False
    stopped: bool = False
    held_types: set[str] = field(default_factory=set)

    async def pause(self) -> None:
        self.paused = True

    async def resume(self) -> None:
        self.paused = False
        self.queue._dispatch()

    async def stop(self) -> None:
        self.stopped = True
        self.queue._release(self)


class InMemoryQueue:
    def __init__(self) -> None:
        self._declared: set[str] = set()
        self._ready: dict[str, deque[_Message]] = {}
        self._held: dict[int, _Held] = {}
        self._consumers: list[_MemoryConsumer] = []
        self._tags = itertools.count(1)
        self._tasks: set[asyncio.Task[None]] = set()
        self.force_outcome: PublishOutcome | None = None

    async def declare_queue(self, job_type: str) -> None:
        self._declared.add(job_type)
        self._ready.setdefault(job_type, deque())

    async def publish(
        self, routing_key: str, body: bytes, headers: Mapping[str, str]
    ) -> PublishOutcome:
        if self.force_outcome is not None:
            return self.force_outcome
        if routing_key not in self._declared:
            return PublishOutcome.RETURNED
        self._ready[routing_key].append(_Message(routing_key, body, dict(headers)))
        self._dispatch()
        return PublishOutcome.CONFIRMED

    async def consume(
        self, job_types: Sequence[str], on_delivery: DeliveryCallback
    ) -> _MemoryConsumer:
        consumer = _MemoryConsumer(self, tuple(job_types), on_delivery)
        self._consumers.append(consumer)
        self._dispatch()
        return consumer

    async def ack(self, delivery: Delivery) -> None:
        held = self._held.pop(self._tag(delivery))
        held.consumer.held_types.discard(held.message.routing_key)
        self._dispatch()

    async def nack_requeue(self, delivery: Delivery) -> None:
        held = self._held.pop(self._tag(delivery))
        held.consumer.held_types.discard(held.message.routing_key)
        held.message.redelivered = True
        self._ready[held.message.routing_key].appendleft(held.message)
        self._dispatch()

    async def close(self) -> None:
        for consumer in list(self._consumers):
            await consumer.stop()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # --- internals ---------------------------------------------------------------------------

    @staticmethod
    def _tag(delivery: Delivery) -> int:
        assert isinstance(delivery.handle, int)
        return delivery.handle

    def _release(self, consumer: _MemoryConsumer) -> None:
        """A stopped consumer gives back what it holds; the messages go to the front again."""
        for tag, held in list(self._held.items()):
            if held.consumer is consumer:
                del self._held[tag]
                held.message.redelivered = True
                self._ready[held.message.routing_key].appendleft(held.message)
        consumer.held_types.clear()
        self._consumers = [c for c in self._consumers if c is not consumer]
        self._dispatch()

    @staticmethod
    async def _run(consumer: _MemoryConsumer, delivery: Delivery) -> None:
        await consumer.on_delivery(delivery)

    def _dispatch(self) -> None:
        """Give each active consumer at most one unacknowledged message per queue."""
        for consumer in list(self._consumers):
            if consumer.paused or consumer.stopped:
                continue
            for job_type in consumer.job_types:
                ready = self._ready.get(job_type)
                if not ready or job_type in consumer.held_types:
                    continue
                message = ready.popleft()
                tag = next(self._tags)
                self._held[tag] = _Held(message, consumer)
                consumer.held_types.add(job_type)
                delivery = Delivery(
                    routing_key=message.routing_key,
                    body=message.body,
                    headers=message.headers,
                    redelivered=message.redelivered,
                    handle=tag,
                )
                task = asyncio.get_running_loop().create_task(self._run(consumer, delivery))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
