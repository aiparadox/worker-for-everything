"""Settings read from the environment and checked when a process starts."""

from qfe.config.loader import EXIT_CODE_BAD_CONFIG, load_or_exit
from qfe.config.settings import (
    ApiSettings,
    MaintenanceSettings,
    MigrateSettings,
    RelaySettings,
    WorkerSettings,
)

__all__ = [
    "EXIT_CODE_BAD_CONFIG",
    "ApiSettings",
    "MaintenanceSettings",
    "MigrateSettings",
    "RelaySettings",
    "WorkerSettings",
    "load_or_exit",
]
