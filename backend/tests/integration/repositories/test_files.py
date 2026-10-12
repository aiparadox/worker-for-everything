"""The files repository against a real PostgreSQL (spec FEAT-20261010-1211)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from qfe.adapters.postgres.files import PostgresFileRepository
from qfe.ports.repositories import FileKind
from tests.integration.repositories.conftest import AccountFactory, AdminSql, FileFactory


async def test_a_new_file_is_pending_with_an_expiry(
    files: PostgresFileRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    file_id = await files.create_file(
        organisation_id=account.organisation_id,
        kind=FileKind.INPUT,
        storage_key="orgs/x/one",
        display_name="scan.pdf",
        content_type="application/pdf",
        size_bytes=42,
        expires_in=timedelta(hours=2),
    )
    record = await files.get_file(organisation_id=account.organisation_id, file_id=file_id)
    assert record is not None
    assert (record.kind, record.status, record.size_bytes) == ("input", "pending", 42)
    assert record.storage_key == "orgs/x/one"
    assert record.expires_at is not None
    assert (
        timedelta(hours=1, minutes=59) < record.expires_at - datetime.now(UTC) < timedelta(hours=2)
    )


async def test_a_file_without_an_expiry_has_none(
    files: PostgresFileRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    file_id = await files.create_file(
        organisation_id=account.organisation_id,
        kind=FileKind.RESULT,
        storage_key="orgs/x/result",
        display_name="out.json",
        content_type="application/json",
        size_bytes=1,
        expires_in=None,
    )
    record = await files.get_file(organisation_id=account.organisation_id, file_id=file_id)
    assert record is not None
    assert (record.kind, record.expires_at) == ("result", None)


async def test_a_storage_key_can_be_used_only_once(
    files: PostgresFileRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    kwargs = {
        "organisation_id": account.organisation_id,
        "kind": FileKind.INPUT,
        "storage_key": "orgs/x/dup",
        "display_name": "a",
        "content_type": "text/plain",
        "size_bytes": 1,
        "expires_in": None,
    }
    await files.create_file(**kwargs)  # type: ignore[arg-type]
    with pytest.raises(IntegrityError):
        await files.create_file(**kwargs)  # type: ignore[arg-type]


async def test_a_file_is_only_visible_to_its_own_organisation(
    files: PostgresFileRepository, make_account: AccountFactory, make_file: FileFactory
) -> None:
    mine = await make_account()
    other = await make_account()
    file_id = await make_file(mine)
    assert await files.get_file(organisation_id=mine.organisation_id, file_id=file_id)
    assert await files.get_file(organisation_id=other.organisation_id, file_id=file_id) is None
    assert await files.get_file(organisation_id=mine.organisation_id, file_id=uuid.uuid4()) is None


async def test_marking_available_clears_the_expiry_and_can_be_repeated(
    files: PostgresFileRepository, make_account: AccountFactory, make_file: FileFactory
) -> None:
    account = await make_account()
    pending = await make_file(account, available=False)
    before = await files.get_file(organisation_id=account.organisation_id, file_id=pending)
    assert before is not None and before.status == "pending" and before.expires_at is not None
    for _ in range(2):
        updated = await files.mark_files_available(
            organisation_id=account.organisation_id, file_ids=[pending]
        )
        assert updated == [pending]
    after = await files.get_file(organisation_id=account.organisation_id, file_id=pending)
    assert after is not None
    assert (after.status, after.expires_at) == ("available", None)


async def test_marking_never_touches_another_organisations_files(
    files: PostgresFileRepository,
    make_account: AccountFactory,
    make_file: FileFactory,
    admin: AdminSql,
) -> None:
    mine = await make_account()
    other = await make_account()
    theirs = await make_file(other, available=False)
    assert (
        await files.mark_files_available(organisation_id=mine.organisation_id, file_ids=[theirs])
        == []
    )
    assert await admin.scalar("SELECT status FROM files WHERE id = :i", i=theirs) == "pending"


async def test_marking_an_empty_list_does_nothing(
    files: PostgresFileRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    assert (
        await files.mark_files_available(organisation_id=account.organisation_id, file_ids=[]) == []
    )


async def test_marking_several_files_at_once(
    files: PostgresFileRepository, make_account: AccountFactory, make_file: FileFactory
) -> None:
    account = await make_account()
    ids = [await make_file(account, available=False) for _ in range(3)]
    updated = await files.mark_files_available(
        organisation_id=account.organisation_id, file_ids=ids
    )
    assert set(updated) == set(ids)
