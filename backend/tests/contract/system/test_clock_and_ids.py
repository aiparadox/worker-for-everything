"""The fakes and the real implementations all pass the same contracts."""

import pytest

from qfe.adapters.system import SecretsIdGenerator, SystemClock
from qfe.ports import Clock, IdGenerator
from tests.contract.system.suite import ClockContract, IdGeneratorContract
from tests.fakes.clock import FakeClock, SequenceIdGenerator


class TestSystemClock(ClockContract):
    @pytest.fixture
    def clock(self) -> Clock:
        return SystemClock()


class TestFakeClock(ClockContract):
    @pytest.fixture
    def clock(self) -> Clock:
        return FakeClock()


class TestSecretsIdGenerator(IdGeneratorContract):
    @pytest.fixture
    def ids(self) -> IdGenerator:
        return SecretsIdGenerator()


class TestSequenceIdGenerator(IdGeneratorContract):
    @pytest.fixture
    def ids(self) -> IdGenerator:
        return SequenceIdGenerator()


def test_the_fake_clock_moves_only_when_told() -> None:
    clock = FakeClock()
    start = clock.now()
    assert clock.now() == start
    clock.advance(90)
    assert (clock.now() - start).total_seconds() == 90
