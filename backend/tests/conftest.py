"""Markers are set from the folder a test is in, so nobody has to remember to tag a test."""

import pytest

LEVELS = ("unit", "integration", "contract", "e2e")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.path).replace("\\", "/")
        for level in LEVELS:
            if f"/tests/{level}/" in path:
                item.add_marker(getattr(pytest.mark, level))
