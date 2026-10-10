"""The contract every StorageAdapter must pass.

Uploading through a presigned link needs the real service, so it is covered by the SeaweedFS
checks (FEAT-20261010-1209); this suite covers what the server itself does with objects.
"""

import uuid
from collections.abc import AsyncIterator

import pytest

from qfe.ports import ObjectNotFound, StorageAdapter


class StorageAdapterContract:
    @pytest.fixture
    def storage(self) -> StorageAdapter:  # the subclass overrides this fixture
        raise NotImplementedError

    @pytest.fixture
    def key(self) -> str:
        return f"orgs/contract/{uuid.uuid4().hex}"

    async def test_ensure_bucket_can_be_repeated(self, storage: StorageAdapter) -> None:
        await storage.ensure_bucket()
        await storage.ensure_bucket()

    async def test_a_missing_object_has_no_info(self, storage: StorageAdapter, key: str) -> None:
        await storage.ensure_bucket()
        assert await storage.head_object(key) is None

    async def test_a_written_object_can_be_inspected_and_read(
        self, storage: StorageAdapter, key: str
    ) -> None:
        await storage.ensure_bucket()
        await storage.write_object(key, b"hello world", "text/plain")
        info = await storage.head_object(key)
        assert info is not None
        assert info.size_bytes == len(b"hello world")
        assert info.content_type == "text/plain"
        assert b"".join([chunk async for chunk in storage.read_object(key)]) == b"hello world"

    async def test_a_stream_can_be_written(self, storage: StorageAdapter, key: str) -> None:
        await storage.ensure_bucket()

        async def parts() -> AsyncIterator[bytes]:
            yield b"abc"
            yield b"def"

        await storage.write_object(key, parts(), "application/octet-stream")
        assert b"".join([chunk async for chunk in storage.read_object(key)]) == b"abcdef"

    async def test_reading_a_missing_object_raises_not_found(
        self, storage: StorageAdapter, key: str
    ) -> None:
        await storage.ensure_bucket()
        with pytest.raises(ObjectNotFound):
            [chunk async for chunk in storage.read_object(key)]

    async def test_delete_says_whether_the_object_existed(
        self, storage: StorageAdapter, key: str
    ) -> None:
        await storage.ensure_bucket()
        await storage.write_object(key, b"x", "text/plain")
        assert await storage.delete_object(key) is True
        assert await storage.delete_object(key) is False  # a missing object is not an error
        assert await storage.head_object(key) is None

    async def test_signing_an_upload_names_the_key(self, storage: StorageAdapter, key: str) -> None:
        upload = await storage.create_presigned_upload(key, "text/plain", 1024, 60)
        assert upload.url
        assert key in upload.url or key in upload.fields.values()

    async def test_a_download_link_is_returned(self, storage: StorageAdapter, key: str) -> None:
        link = await storage.create_presigned_download(key, 60)
        assert link
        assert key in link
