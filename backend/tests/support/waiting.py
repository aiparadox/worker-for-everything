"""Waiting for something asynchronous to happen, with a clear failure when it does not."""

import asyncio
from collections.abc import Callable

DEFAULT_SECONDS = 5.0


async def eventually(condition: Callable[[], bool], *, seconds: float = DEFAULT_SECONDS) -> None:
    """Poll ``condition`` until it is true or ``seconds`` have passed."""
    deadline = asyncio.get_running_loop().time() + seconds
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"condition not met within {seconds:g}s")
        await asyncio.sleep(0.01)


async def stays_true(condition: Callable[[], bool], *, seconds: float = 0.3) -> None:
    """Check that ``condition`` is true now and stays true for ``seconds`` (for "nothing else
    arrives" checks)."""
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        if not condition():
            raise AssertionError("condition stopped being true")
        await asyncio.sleep(0.01)
