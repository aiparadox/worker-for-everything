"""An in-memory StorageAdapter.

Fake-only helpers (not part of the port): ``simulate_upload`` plays the client side of a presigned
upload, enforcing the size range; ``go_down`` makes calls that need storage raise
``StorageUnavailable`` (signing stays available, as with the real service).
"""

from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

from qfe.ports import ObjectInfo, ObjectNotFound, PresignedUpload, StorageUnavailable


@dataclass
class _Stored:
    data: bytes
    content_type: str | None


class UploadRejected(Exception):
    """The simulated storage refused an upload (size outside the signed range, wrong key)."""


class InMemoryStorage:
    def __init__(self) -> None:
        self._objects: dict[str, _Stored] = {}
        self._bucket_ready = False
        self._down = False
        self._signed: dict[str, tuple[str, int]] = {}  # upload url -> (key, max size)

    def go_down(self) -> None:
        self._down = True

    def come_back(self) -> None:
        self._down = False

    def _check_up(self) -> None:
        if self._down:
            raise StorageUnavailable("storage is down")

    async def ensure_bucket(self) -> None:
        self._check_up()
        self._bucket_ready = True

    async def create_presigned_upload(
        self,
        storage_key: str,
        content_type: str,
        max_size_bytes: int,
        expires_in_seconds: int,
    ) -> PresignedUpload:
        url = f"memory://bucket/{storage_key}?expires_in={expires_in_seconds}"
        self._signed[url] = (storage_key, max_size_bytes)
        return PresignedUpload(url=url, fields={"key": storage_key, "Content-Type": content_type})

    async def create_presigned_download(self, storage_key: str, expires_in_seconds: int) -> str:
        return f"memory://bucket/{storage_key}?download&expires_in={expires_in_seconds}"

    async def head_object(self, storage_key: str) -> ObjectInfo | None:
        self._check_up()
        stored = self._objects.get(storage_key)
        return None if stored is None else ObjectInfo(len(stored.data), stored.content_type)

    async def delete_object(self, storage_key: str) -> bool:
        self._check_up()
        return self._objects.pop(storage_key, None) is not None

    async def read_object(self, storage_key: str) -> AsyncIterator[bytes]:
        self._check_up()
        stored = self._objects.get(storage_key)
        if stored is None:
            raise ObjectNotFound(storage_key)
        chunk = 4
        for start in range(0, len(stored.data), chunk):
            yield stored.data[start : start + chunk]

    async def write_object(
        self, storage_key: str, data: bytes | AsyncIterable[bytes], content_type: str
    ) -> None:
        self._check_up()
        content = data if isinstance(data, bytes) else b"".join([part async for part in data])
        self._objects[storage_key] = _Stored(content, content_type)

    def simulate_upload(self, upload: PresignedUpload, data: bytes) -> None:
        """The client posts a file to a presigned upload."""
        key, max_size = self._signed[upload.url]
        if not 1 <= len(data) <= max_size:
            raise UploadRejected(f"size {len(data)} outside 1..{max_size}")
        self._objects[key] = _Stored(data, upload.fields.get("Content-Type"))
