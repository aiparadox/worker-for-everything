"""The contract every QueueAdapter must pass (docs/ARCHITECTURE.md section 13).

A test module subclasses ``QueueAdapterContract`` (name starting with ``Test``) and provides the
``queue`` fixture. The fake and, later, the RabbitMQ adapter run the same tests.
"""

import uuid

import pytest

from qfe.ports import Delivery, PublishOutcome, QueueAdapter
from tests.support.waiting import eventually, stays_true


class Recorder:
    """Collects deliveries; does not acknowledge them unless asked."""

    def __init__(self) -> None:
        self.deliveries: list[Delivery] = []

    async def __call__(self, delivery: Delivery) -> None:
        self.deliveries.append(delivery)

    @property
    def bodies(self) -> list[bytes]:
        return [d.body for d in self.deliveries]


class QueueAdapterContract:
    @pytest.fixture
    def queue(self) -> QueueAdapter:  # the subclass overrides this fixture
        raise NotImplementedError

    @pytest.fixture
    def job_type(self) -> str:
        return f"contract.{uuid.uuid4().hex[:12]}"

    async def test_publish_to_a_declared_queue_is_confirmed(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        assert await queue.publish(job_type, b"x", {}) is PublishOutcome.CONFIRMED

    async def test_publish_without_a_queue_is_reported_as_returned(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        assert await queue.publish(job_type, b"x", {}) is PublishOutcome.RETURNED

    async def test_declaring_twice_is_harmless(self, queue: QueueAdapter, job_type: str) -> None:
        await queue.declare_queue(job_type)
        await queue.declare_queue(job_type)
        assert await queue.publish(job_type, b"x", {}) is PublishOutcome.CONFIRMED

    async def test_a_consumer_receives_body_and_headers(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        recorder = Recorder()
        consumer = await queue.consume([job_type], recorder)
        await queue.publish(job_type, b"hello", {"trace_id": "t1", "traceparent": "tp"})
        await eventually(lambda: len(recorder.deliveries) == 1)
        delivery = recorder.deliveries[0]
        assert delivery.body == b"hello"
        assert delivery.headers["trace_id"] == "t1"
        assert delivery.routing_key == job_type
        assert delivery.redelivered is False
        await queue.ack(delivery)
        await consumer.stop()

    async def test_messages_wait_in_the_queue_until_a_consumer_starts(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        await queue.publish(job_type, b"early", {})
        recorder = Recorder()
        consumer = await queue.consume([job_type], recorder)
        await eventually(lambda: recorder.bodies == [b"early"])
        await queue.ack(recorder.deliveries[0])
        await consumer.stop()

    async def test_each_job_type_has_its_own_queue(self, queue: QueueAdapter) -> None:
        first, second = (f"contract.{uuid.uuid4().hex[:12]}" for _ in range(2))
        await queue.declare_queue(first)
        await queue.declare_queue(second)
        on_first, on_second = Recorder(), Recorder()
        consumer_first = await queue.consume([first], on_first)
        consumer_second = await queue.consume([second], on_second)
        await queue.publish(first, b"for-first", {})
        await queue.publish(second, b"for-second", {})
        await eventually(
            lambda: on_first.bodies == [b"for-first"] and on_second.bodies == [b"for-second"]
        )
        await queue.ack(on_first.deliveries[0])
        await queue.ack(on_second.deliveries[0])
        await consumer_first.stop()
        await consumer_second.stop()

    async def test_an_acknowledged_message_is_not_delivered_again(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        first = Recorder()
        consumer = await queue.consume([job_type], first)
        await queue.publish(job_type, b"once", {})
        await eventually(lambda: len(first.deliveries) == 1)
        await queue.ack(first.deliveries[0])
        await consumer.stop()
        second = Recorder()
        again = await queue.consume([job_type], second)
        await stays_true(lambda: second.deliveries == [])
        await again.stop()

    async def test_nack_requeue_delivers_the_message_again_marked_redelivered(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        recorder = Recorder()
        consumer = await queue.consume([job_type], recorder)
        await queue.publish(job_type, b"again", {})
        await eventually(lambda: len(recorder.deliveries) == 1)
        await queue.nack_requeue(recorder.deliveries[0])
        await eventually(lambda: len(recorder.deliveries) == 2)
        assert recorder.deliveries[1].body == b"again"
        assert recorder.deliveries[1].redelivered is True
        await queue.ack(recorder.deliveries[1])
        await consumer.stop()

    async def test_an_unacknowledged_message_comes_back_when_the_consumer_stops(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        first = Recorder()
        consumer = await queue.consume([job_type], first)
        await queue.publish(job_type, b"unacked", {})
        await eventually(lambda: len(first.deliveries) == 1)
        await consumer.stop()  # the message was never acknowledged
        second = Recorder()
        again = await queue.consume([job_type], second)
        await eventually(lambda: second.bodies == [b"unacked"])
        assert second.deliveries[0].redelivered is True
        await queue.ack(second.deliveries[0])
        await again.stop()

    async def test_a_consumer_holds_at_most_one_unacknowledged_message_per_queue(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        recorder = Recorder()
        consumer = await queue.consume([job_type], recorder)
        for index in range(3):
            await queue.publish(job_type, str(index).encode(), {})
        await eventually(lambda: len(recorder.deliveries) == 1)
        await stays_true(lambda: len(recorder.deliveries) == 1)
        await queue.ack(recorder.deliveries[0])
        await eventually(lambda: len(recorder.deliveries) == 2)
        await queue.ack(recorder.deliveries[1])
        await eventually(lambda: len(recorder.deliveries) == 3)
        await queue.ack(recorder.deliveries[2])
        assert recorder.bodies == [b"0", b"1", b"2"]
        await consumer.stop()

    async def test_pause_stops_new_deliveries_and_resume_restarts_them(
        self, queue: QueueAdapter, job_type: str
    ) -> None:
        await queue.declare_queue(job_type)
        recorder = Recorder()
        consumer = await queue.consume([job_type], recorder)
        await consumer.pause()
        await queue.publish(job_type, b"while-paused", {})
        await stays_true(lambda: recorder.deliveries == [])
        await consumer.resume()
        await eventually(lambda: recorder.bodies == [b"while-paused"])
        await queue.ack(recorder.deliveries[0])
        await consumer.stop()
