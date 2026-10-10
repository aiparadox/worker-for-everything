"""The in-memory fake passes the queue contract, and shows the outcomes a real broker cannot be
told to produce."""

from collections.abc import AsyncIterator

import pytest

from qfe.ports import PublishOutcome, QueueAdapter
from tests.contract.queue.suite import QueueAdapterContract
from tests.fakes.memory_queue import InMemoryQueue


class TestInMemoryQueue(QueueAdapterContract):
    @pytest.fixture
    async def queue(self) -> AsyncIterator[QueueAdapter]:
        fake = InMemoryQueue()
        yield fake
        await fake.close()


@pytest.mark.parametrize("outcome", [PublishOutcome.REJECTED, PublishOutcome.UNKNOWN])
async def test_the_fake_can_be_told_to_report_rejected_or_unknown(outcome: PublishOutcome) -> None:
    fake = InMemoryQueue()
    await fake.declare_queue("t")
    fake.force_outcome = outcome
    assert await fake.publish("t", b"x", {}) is outcome
