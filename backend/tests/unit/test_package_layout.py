"""Checks that the folder layout from docs/specs/FEAT-20261010-1201-repo-layout.md exists."""

import importlib

import pytest

SUBPACKAGES = [
    "domain",
    "ports",
    "application",
    "job_types",
    "handlers",
    "api",
    "worker",
    "relay",
    "maintenance",
    "observability",
    "config",
    "adapters",
    "adapters.postgres",
    "adapters.rabbitmq",
    "adapters.s3",
    "adapters.valkey",
    "adapters.password_auth",
    "adapters.system",
]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    importlib.import_module(f"qfe.{name}")
