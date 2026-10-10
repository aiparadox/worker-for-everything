"""The contract every RateLimiter must pass.

The adapter under test is built with ``LIMIT`` requests per ``WINDOW_SECONDS`` for every class.
``advance_past_window`` moves time past the end of the window: the fake moves its clock, a real
adapter waits.
"""

import uuid
from collections.abc import Awaitable, Callable

import pytest

from qfe.ports import LimitClass, Rate, RateLimiter

LIMIT = 3
WINDOW_SECONDS = 2
RATE = Rate(limit=LIMIT, window_seconds=WINDOW_SECONDS)


class RateLimiterContract:
    @pytest.fixture
    def limiter(self) -> RateLimiter:  # the subclass overrides this fixture
        raise NotImplementedError

    @pytest.fixture
    def advance_past_window(self) -> Callable[[], Awaitable[None]]:  # and this one
        raise NotImplementedError

    @pytest.fixture
    def subject(self) -> str:
        return f"subject-{uuid.uuid4().hex[:10]}"

    async def test_requests_up_to_the_limit_are_allowed_with_a_shrinking_count(
        self, limiter: RateLimiter, subject: str
    ) -> None:
        for used in range(1, LIMIT + 1):
            decision = await limiter.check(LimitClass.API_KEY, subject)
            assert decision.allowed
            assert decision.limit == LIMIT
            assert decision.remaining == LIMIT - used
            assert decision.retry_after_seconds == 0

    async def test_the_request_over_the_limit_is_refused_with_a_retry_time(
        self, limiter: RateLimiter, subject: str
    ) -> None:
        for _ in range(LIMIT):
            await limiter.check(LimitClass.API_KEY, subject)
        decision = await limiter.check(LimitClass.API_KEY, subject)
        assert not decision.allowed
        assert decision.remaining == 0
        assert 1 <= decision.retry_after_seconds <= WINDOW_SECONDS
        assert decision.reset_after_seconds >= decision.retry_after_seconds

    async def test_subjects_are_counted_separately(
        self, limiter: RateLimiter, subject: str
    ) -> None:
        for _ in range(LIMIT):
            await limiter.check(LimitClass.API_KEY, subject)
        other = await limiter.check(LimitClass.API_KEY, subject + "-other")
        assert other.allowed

    async def test_classes_are_counted_separately(self, limiter: RateLimiter, subject: str) -> None:
        for _ in range(LIMIT):
            await limiter.check(LimitClass.API_KEY, subject)
        assert (await limiter.check(LimitClass.ORGANISATION, subject)).allowed
        assert (await limiter.check(LimitClass.REFRESH, subject)).allowed

    async def test_the_count_starts_again_in_the_next_window(
        self,
        limiter: RateLimiter,
        advance_past_window: Callable[[], Awaitable[None]],
        subject: str,
    ) -> None:
        for _ in range(LIMIT + 1):
            await limiter.check(LimitClass.AUTH_ATTEMPT, subject)
        assert not (await limiter.check(LimitClass.AUTH_ATTEMPT, subject)).allowed
        await advance_past_window()
        assert (await limiter.check(LimitClass.AUTH_ATTEMPT, subject)).allowed
