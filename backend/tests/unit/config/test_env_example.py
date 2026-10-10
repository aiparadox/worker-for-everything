"""The committed .env.example must stay valid for every process, and list every tuning setting."""

import os
import re
from pathlib import Path

import pytest

from qfe.config import (
    ApiSettings,
    MaintenanceSettings,
    MigrateSettings,
    RelaySettings,
    WorkerSettings,
    load_or_exit,
)
from qfe.config.base import QfeSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[4] / ".env.example"
ALL_CLASSES: list[type[QfeSettings]] = [
    ApiSettings,
    WorkerSettings,
    RelaySettings,
    MaintenanceSettings,
    MigrateSettings,
]


def read_values(*, include_commented: bool) -> dict[str, str]:
    pattern = r"^#?\s*(QFE_[A-Z0-9_]+)=(.*)$" if include_commented else r"^(QFE_[A-Z0-9_]+)=(.*)$"
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(pattern, line)
        if match:
            values[match.group(1)] = match.group(2)
    # Compose reads the file top to bottom and fills in ${NAME} from names defined above it.
    resolved: dict[str, str] = {}
    for name, value in values.items():
        resolved[name] = re.sub(r"\$\{(\w+)\}", lambda m: resolved[m.group(1)], value)
    return resolved


@pytest.fixture
def example_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("QFE_"):
            monkeypatch.delenv(name)
    for name, value in read_values(include_commented=False).items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("settings_class", ALL_CLASSES)
def test_example_is_valid_for_every_process(
    example_environment: None, settings_class: type[QfeSettings]
) -> None:
    assert load_or_exit(settings_class) is not None


def test_every_setting_with_a_default_is_listed_as_a_tuning_line() -> None:
    listed = read_values(include_commented=True)
    for settings_class in ALL_CLASSES:
        for field_name, field in settings_class.model_fields.items():
            variable = f"QFE_{field_name.upper()}"
            assert variable in listed, f"{variable} is missing from .env.example"
            if not field.is_required() and field.default is not None:
                assert listed[variable] == str(field.default), f"default differs for {variable}"
