"""Readiness checks: is each dependency reachable?

A check is a small async function registered by the module that owns the dependency. They run at
the same time, each with a timeout. Only a *critical* dependency being down makes the process
not ready; the others are reported as ``degraded`` (docs/specs/FEAT-20261010-1205-...).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

CheckFunction = Callable[[], Awaitable[None]]
CheckStatus = Literal["ok", "down"]

DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    check: CheckFunction
    critical: bool


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    critical: bool
    duration_ms: int
    error: str | None = None


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    results: list[CheckResult]

    def as_dict(self) -> dict[str, object]:
        degraded = [r.name for r in self.results if r.status == "down" and not r.critical]
        return {
            "status": "ready" if self.ready else "not_ready",
            "degraded": degraded,
            "checks": {
                r.name: {
                    "status": r.status,
                    "critical": r.critical,
                    "duration_ms": r.duration_ms,
                    **({"error": r.error} if r.error else {}),
                }
                for r in self.results
            },
        }


async def _run_one(item: ReadinessCheck, limit_seconds: float) -> CheckResult:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(item.check(), timeout=limit_seconds)
        status: CheckStatus = "ok"
        error = None
    except TimeoutError:
        status, error = "down", f"timed out after {limit_seconds:g}s"
    except Exception as exc:  # a failing dependency must never crash /readyz
        # The class name only: the message may contain a connection URL with a password.
        status, error = "down", type(exc).__name__
    duration_ms = int((time.perf_counter() - started) * 1000)
    return CheckResult(item.name, status, item.critical, duration_ms, error)


async def run_checks(
    checks: list[ReadinessCheck], limit_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> ReadinessReport:
    results = list(await asyncio.gather(*(_run_one(item, limit_seconds) for item in checks)))
    ready = all(r.status == "ok" for r in results if r.critical)
    return ReadinessReport(ready=ready, results=results)
