"""The storage port: where uploaded files and result files live.

The first implementation is SeaweedFS through its S3 API (D20). Clients upload straight to storage
through a presigned POST; the server only signs, checks and deletes. Errors are typed so callers
can tell "not there" from "cannot reach storage".
"""

from collections.abc import AsyncIterable, AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Protocol


class StorageError(Exception):
    """Base class for storage failures."""


class StorageUnavailable(StorageError):
    """Storage could not be reached or did not answer in time."""


class ObjectNotFound(StorageError):
    """The object does not exist."""


@dataclass(frozen=True)
class PresignedUpload:
    """What a client needs to upload one file: POST ``fields`` and the file to ``url``."""

    url: str
    fields: Mapping[str, str]


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int
    content_type: str | None


class StorageAdapter(Protocol):
    async def ensure_bucket(self) -> None:
        """Create the bucket (and its expiry rule) if absent. Safe to repeat."""
        ...

    async def create_presigned_upload(
        self,
        storage_key: str,
        content_type: str,
        max_size_bytes: int,
        expires_in_seconds: int,
    ) -> PresignedUpload:
        """Sign an upload for exactly one key, with a size range of 1 to ``max_size_bytes``.
        Signing is local: it works even while storage is down."""
        ...

    async def create_presigned_download(self, storage_key: str, expires_in_seconds: int) -> str:
        """A short-lived link to read the object. Generated on read, never stored."""
        ...

    async def head_object(self, storage_key: str) -> ObjectInfo | None:
        """Size and type of the object, or ``None`` if it does not exist."""
        ...

    async def delete_object(self, storage_key: str) -> bool:
        """Delete the object. ``True`` if it existed, ``False`` if it did not (not an error)."""
        ...

    def read_object(self, storage_key: str) -> AsyncIterator[bytes]:
        """Stream the object's bytes. Raises ``ObjectNotFound`` if it does not exist."""
        ...

    async def write_object(
        self, storage_key: str, data: bytes | AsyncIterable[bytes], content_type: str
    ) -> None:
        """Store a result file (from a handler)."""
        ...
