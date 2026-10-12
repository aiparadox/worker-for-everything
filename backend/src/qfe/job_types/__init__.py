"""The light definitions of the job types the system can run. Importing this package must stay
cheap: no handlers, no adapters, no OCR or AI libraries."""

from qfe.job_types.base import InputModel, OutputModel
from qfe.job_types.definition import JobTypeDefinition
from qfe.job_types.errors import (
    InvalidPayload,
    PermanentError,
    Problem,
    UnknownJobType,
)
from qfe.job_types.file_ref import FileRef, find_file_refs
from qfe.job_types.registry import JobTypeRegistry, ValidatedPayload, default_registry

__all__ = [
    "FileRef",
    "InputModel",
    "InvalidPayload",
    "JobTypeDefinition",
    "JobTypeRegistry",
    "OutputModel",
    "PermanentError",
    "Problem",
    "UnknownJobType",
    "ValidatedPayload",
    "default_registry",
    "find_file_refs",
]
