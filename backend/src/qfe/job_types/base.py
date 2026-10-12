"""Base classes for a job type's input and output.

Inputs reject unknown fields: a client that misspells a field gets an error instead of a job that
silently ignores it (docs/specs/FEAT-20261010-1212-job-type-registry.md, question 3).
"""

from pydantic import BaseModel, ConfigDict


class InputModel(BaseModel):
    """The input of a job type. Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")


class OutputModel(BaseModel):
    """The result of a job type."""

    model_config = ConfigDict(extra="forbid")
