"""The in-memory fake passes the storage contract; plus the behaviour only the fake can show."""

import pytest

from qfe.ports import StorageAdapter, StorageUnavailable
from tests.contract.storage.suite import StorageAdapterContract
from tests.fakes.memory_storage import InMemoryStorage, UploadRejected


class TestInMemoryStorage(StorageAdapterContract):
    @pytest.fixture
    def storage(self) -> StorageAdapter:
        return InMemoryStorage()


async def test_the_simulated_upload_enforces_the_signed_size_range() -> None:
    storage = InMemoryStorage()
    upload = await storage.create_presigned_upload("k", "text/plain", 10, 60)
    storage.simulate_upload(upload, b"ok")
    assert (await storage.head_object("k")) is not None
    with pytest.raises(UploadRejected):
        storage.simulate_upload(upload, b"x" * 11)
    with pytest.raises(UploadRejected):
        storage.simulate_upload(upload, b"")


async def test_when_down_calls_fail_but_signing_still_works() -> None:
    storage = InMemoryStorage()
    storage.go_down()
    assert await storage.create_presigned_upload("k", "text/plain", 10, 60)
    with pytest.raises(StorageUnavailable):
        await storage.head_object("k")
    storage.come_back()
    assert await storage.head_object("k") is None
