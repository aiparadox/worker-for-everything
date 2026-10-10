"""The in-memory fake passes the rate limiter contract; plus its store-down behaviour."""

from collections.abc import Awaitable, Callable

import pytest

from qfe.ports import LimitClass, RateLimiter, RateLimiterUnavailable
from tests.contract.rate_limiter.suite import RATE, WINDOW_SECONDS, RateLimiterContract
from tests.fakes.clock import FakeClock
from tests.fakes.memory_rate_limiter import InMemoryRateLimiter


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def memory_limiter(clock: FakeClock) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(dict.fromkeys(LimitClass, RATE), clock)


class TestInMemoryRateLimiter(RateLimiterContract):
    @pytest.fixture
    def limiter(self, memory_limiter: InMemoryRateLimiter) -> RateLimiter:
        return memory_limiter

    @pytest.fixture
    def advance_past_window(self, clock: FakeClock) -> Callable[[], Awaitable[None]]:
        async def advance() -> None:
            clock.advance(WINDOW_SECONDS + 1)

        return advance


async def test_when_the_store_is_down_check_raises_unavailable(
    memory_limiter: InMemoryRateLimiter,
) -> None:
    memory_limiter.go_down()
    with pytest.raises(RateLimiterUnavailable):
        await memory_limiter.check(LimitClass.API_KEY, "s")
    memory_limiter.come_back()
    assert (await memory_limiter.check(LimitClass.API_KEY, "s")).allowed
