"""Readiness checks: critical and non-critical dependencies, timeouts, no leaked details."""

import asyncio

from qfe.observability import ReadinessCheck, run_checks


async def fine() -> None:
    return None


async def broken() -> None:
    raise ConnectionError("postgresql://user:secret-password@host/db refused")


async def hangs() -> None:
    await asyncio.sleep(30)


async def test_everything_ok_is_ready() -> None:
    report = await run_checks([ReadinessCheck("a", fine, True), ReadinessCheck("b", fine, False)])
    assert report.ready
    assert report.as_dict()["status"] == "ready"
    assert report.as_dict()["degraded"] == []


async def test_a_critical_dependency_down_is_not_ready() -> None:
    report = await run_checks([ReadinessCheck("postgres", broken, True)])
    assert not report.ready
    assert report.as_dict()["status"] == "not_ready"


async def test_a_non_critical_dependency_down_is_degraded_but_ready() -> None:
    report = await run_checks(
        [ReadinessCheck("postgres", fine, True), ReadinessCheck("valkey", broken, False)]
    )
    assert report.ready
    assert report.as_dict()["degraded"] == ["valkey"]


async def test_a_hanging_check_returns_within_the_limit() -> None:
    started = asyncio.get_running_loop().time()
    report = await run_checks([ReadinessCheck("slow", hangs, True)], limit_seconds=0.05)
    assert asyncio.get_running_loop().time() - started < 1
    assert not report.ready
    assert "timed out" in str(report.results[0].error)


async def test_the_error_text_never_contains_the_exception_message() -> None:
    report = await run_checks([ReadinessCheck("db", broken, False)])
    text = str(report.as_dict())
    assert "secret-password" not in text
    assert "ConnectionError" in text
