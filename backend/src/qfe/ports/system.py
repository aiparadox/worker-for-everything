"""Small ports that let tests control time and randomness.

Anything compared with "now" inside the database uses the database clock (DATABASE.md section 2);
``Clock`` is for times the application itself needs, such as token expiry. Primary keys are made by
Postgres (D41), so ``IdGenerator`` only makes random values the application must create itself:
lease tokens, token ids, the secret part of an API key.
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time as a timezone-aware UTC datetime."""
        ...


class IdGenerator(Protocol):
    def new_token(self) -> str:
        """A new random, URL-safe string that cannot be guessed (at least 128 bits)."""
        ...
