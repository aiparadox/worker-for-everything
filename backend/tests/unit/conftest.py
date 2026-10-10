"""Shared fixtures for unit tests."""

import pytest

from qfe.observability import setup_tracing


@pytest.fixture(scope="session", autouse=True)
def tracing() -> None:
    """Install the tracer provider once. OpenTelemetry allows setting it only once per process.
    Telemetry is off, so nothing is exported, but trace ids are real."""
    setup_tracing("qfe-unit-tests", "off", None)
