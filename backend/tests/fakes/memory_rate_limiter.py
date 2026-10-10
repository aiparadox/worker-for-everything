"""An in-memory RateLimiter (fixed window), driven by the Clock port.

Fake-only control: ``go_down`` makes ``check`` raise ``RateLimiterUnavailable``.
"""

import math

from qfe.ports import Clock, Decision, LimitClass, Rate, RateLimiterUnavailable


class InMemoryRateLimiter:
    def __init__(self, rates: dict[LimitClass, Rate], clock: Clock) -> None:
        self._rates = rates
        self._clock = clock
        self._counts: dict[tuple[LimitClass, str, int], int] = {}
        self._down = False

    def go_down(self) -> None:
        self._down = True

    def come_back(self) -> None:
        self._down = False

    async def check(self, limit_class: LimitClass, subject: str) -> Decision:
        if self._down:
            raise RateLimiterUnavailable("counter store is down")
        rate = self._rates[limit_class]
        now = self._clock.now().timestamp()
        window = int(now // rate.window_seconds)
        key = (limit_class, subject, window)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        reset_after = max(1, math.ceil((window + 1) * rate.window_seconds - now))
        allowed = count <= rate.limit
        return Decision(
            allowed=allowed,
            limit=rate.limit,
            remaining=max(0, rate.limit - count),
            reset_after_seconds=reset_after,
            retry_after_seconds=0 if allowed else reset_after,
        )
