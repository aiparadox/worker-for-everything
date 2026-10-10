"""Contracts for Clock and IdGenerator. The real implementations run these too."""

import re
from datetime import UTC, timedelta

import pytest

from qfe.ports import Clock, IdGenerator

MIN_TOKEN_CHARACTERS = 22  # 128 bits in URL-safe base64 need at least 22 characters
URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


class ClockContract:
    @pytest.fixture
    def clock(self) -> Clock:  # the subclass overrides this fixture
        raise NotImplementedError

    def test_now_is_timezone_aware_utc(self, clock: Clock) -> None:
        now = clock.now()
        assert now.tzinfo is not None
        assert now.utcoffset() == timedelta(0)
        assert now.tzinfo == UTC or now.utcoffset() == timedelta(0)

    def test_time_does_not_go_backwards(self, clock: Clock) -> None:
        first = clock.now()
        second = clock.now()
        assert second >= first


class IdGeneratorContract:
    @pytest.fixture
    def ids(self) -> IdGenerator:  # the subclass overrides this fixture
        raise NotImplementedError

    def test_tokens_are_url_safe_and_long_enough(self, ids: IdGenerator) -> None:
        token = ids.new_token()
        assert URL_SAFE.match(token)
        assert len(token) >= MIN_TOKEN_CHARACTERS

    def test_tokens_are_unique(self, ids: IdGenerator) -> None:
        tokens = {ids.new_token() for _ in range(2000)}
        assert len(tokens) == 2000
