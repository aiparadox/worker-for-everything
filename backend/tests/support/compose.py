"""Small helpers to control the Compose test services from a test."""

import subprocess
import time

from tests.support.environment import REPO_ROOT


def compose(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``docker compose --profile test <args>`` in the repository root."""
    return subprocess.run(  # noqa: S603 - fixed command, arguments come from the tests
        ["docker", "compose", "--profile", "test", *args],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def wait_until_healthy(service: str, *, seconds: float = 60) -> None:
    """Wait until the container of ``service`` reports healthy, or fail with its status."""
    deadline = time.monotonic() + seconds
    status = "unknown"
    while time.monotonic() < deadline:
        result = compose("ps", "--format", "{{.Health}}", service)
        status = result.stdout.strip() or result.stderr.strip() or "unknown"
        if status == "healthy":
            return
        time.sleep(1)
    raise AssertionError(f"{service} did not become healthy within {seconds:g}s (status: {status})")
