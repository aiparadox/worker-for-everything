"""The accounts repository against a real PostgreSQL (spec FEAT-20261010-1211)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from qfe.adapters.postgres.accounts import PostgresAccountRepository
from qfe.ports.repositories import (
    AlreadyRefreshed,
    ApiKeyCreated,
    CreateApiKeyResult,
    EmailTaken,
    Expired,
    FamilyExpired,
    NewRefreshToken,
    PrefixTaken,
    ReuseDetected,
    Revoked,
    Rotated,
    RotateResult,
    SlugTaken,
    UnknownToken,
    UserCreated,
)
from tests.integration.repositories.conftest import Account, AccountFactory, AdminSql

REUSE_WINDOW = timedelta(seconds=30)
TOKEN_LIFETIME = timedelta(days=1)
FAMILY_LIFETIME = timedelta(days=30)
KEY_HASH = bytes(range(32))


# --- create user with organisation


async def test_a_new_user_gets_an_identity_an_organisation_and_an_owner_membership(
    accounts: PostgresAccountRepository, admin: AdminSql
) -> None:
    result = await accounts.create_user_with_organisation(
        email="Ada@Example.com",
        password_hash="hash-1",
        display_name="Ada",
        organisation_name="Ada Labs",
        organisation_slug="ada-labs",
    )
    assert isinstance(result, UserCreated)
    assert await admin.scalar("SELECT email FROM users WHERE id = :i", i=result.user_id) == (
        "Ada@Example.com"
    )
    identity = await admin.rows(
        "SELECT provider, provider_subject, secret_hash FROM auth_identities WHERE user_id = :i",
        i=result.user_id,
    )
    assert [tuple(row) for row in identity] == [("password", str(result.user_id), "hash-1")]
    membership = await accounts.read_membership(
        user_id=result.user_id, organisation_id=result.organisation_id
    )
    assert membership is not None
    assert (membership.role, membership.user_status, membership.organisation_status) == (
        "owner",
        "active",
        "active",
    )


async def test_the_same_email_in_another_case_is_taken(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    first = await make_account("same")
    result = await accounts.create_user_with_organisation(
        email=first.email.upper(),
        password_hash="h",
        display_name=None,
        organisation_name="Other",
        organisation_slug="other-slug",
    )
    assert isinstance(result, EmailTaken)


async def test_a_taken_slug_leaves_no_user_behind(
    accounts: PostgresAccountRepository, admin: AdminSql
) -> None:
    await accounts.create_user_with_organisation(
        email="a@example.com",
        password_hash="h",
        display_name=None,
        organisation_name="A",
        organisation_slug="shared-slug",
    )
    result = await accounts.create_user_with_organisation(
        email="b@example.com",
        password_hash="h",
        display_name=None,
        organisation_name="B",
        organisation_slug="shared-slug",
    )
    assert isinstance(result, SlugTaken)
    assert await admin.scalar("SELECT count(*) FROM users WHERE email = 'b@example.com'") == 0
    assert await admin.scalar("SELECT count(*) FROM auth_identities") == 1  # only the first user's


# --- password identity and login


async def test_find_password_identity_ignores_case_and_reports_the_status(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account("grace")
    found = await accounts.find_password_identity("GRACE@example.COM")
    assert found is not None
    assert found.user_id == account.user_id
    assert found.secret_hash == "argon2-hash-placeholder"
    assert found.user_status == "active"
    await admin.run("UPDATE users SET status = 'disabled' WHERE id = :i", i=account.user_id)
    disabled = await accounts.find_password_identity("grace@example.com")
    assert disabled is not None
    assert disabled.user_status == "disabled"
    assert await accounts.find_password_identity("nobody@example.com") is None


async def test_record_login_sets_the_time(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    assert (
        await admin.scalar("SELECT last_login_at FROM users WHERE id = :i", i=account.user_id)
        is None
    )
    await accounts.record_login(account.user_id)
    stamp = await admin.scalar("SELECT last_login_at FROM users WHERE id = :i", i=account.user_id)
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 30


# --- refresh tokens


async def login(
    accounts: PostgresAccountRepository, user_id: uuid.UUID, **kw: timedelta
) -> NewRefreshToken:
    return await accounts.start_login_session(
        user_id=user_id,
        token_lifetime=kw.get("token_lifetime", TOKEN_LIFETIME),
        family_lifetime=kw.get("family_lifetime", FAMILY_LIFETIME),
        ip="203.0.113.7",
        user_agent="tests",
    )


async def rotate(
    accounts: PostgresAccountRepository, token_id: uuid.UUID, **kw: timedelta
) -> RotateResult:
    return await accounts.rotate_refresh_token(
        presented_id=token_id,
        reuse_window=kw.get("reuse_window", REUSE_WINDOW),
        token_lifetime=kw.get("token_lifetime", TOKEN_LIFETIME),
        ip=None,
        user_agent=None,
    )


async def test_a_login_starts_a_family_and_a_token_never_outlives_it(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    token = await login(accounts, account.user_id, token_lifetime=timedelta(days=90))
    assert token.user_id == account.user_id
    assert token.expires_at <= token.family_expires_at
    assert token.family_expires_at - datetime.now(UTC) < FAMILY_LIFETIME + timedelta(minutes=1)


async def test_rotating_gives_a_new_token_in_the_same_family_with_the_same_family_end(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    first = await login(accounts, account.user_id)
    result = await rotate(accounts, first.id)
    assert isinstance(result, Rotated)
    assert result.token.id != first.id
    assert result.token.family_id == first.family_id
    assert result.token.family_expires_at == first.family_expires_at
    assert result.token.expires_at <= first.family_expires_at
    row = (
        await admin.rows(
            "SELECT used_at, replaced_by FROM refresh_tokens WHERE id = :i", i=first.id
        )
    )[0]
    assert row.used_at is not None
    assert row.replaced_by == result.token.id


async def test_a_used_token_shown_again_inside_the_window_is_not_a_theft(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    first = await login(accounts, account.user_id)
    rotated = await rotate(accounts, first.id)
    assert isinstance(rotated, Rotated)
    assert isinstance(await rotate(accounts, first.id), AlreadyRefreshed)
    assert (
        await admin.scalar("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NOT NULL") == 0
    )
    # and the new token still works
    assert isinstance(await rotate(accounts, rotated.token.id), Rotated)


async def test_a_used_token_shown_again_after_the_window_revokes_the_whole_family(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    first = await login(accounts, account.user_id)
    rotated = await rotate(accounts, first.id)
    assert isinstance(rotated, Rotated)
    await asyncio.sleep(0.05)
    assert isinstance(await rotate(accounts, first.id, reuse_window=timedelta(0)), ReuseDetected)
    assert await admin.scalar("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL") == 0
    assert isinstance(
        await rotate(accounts, rotated.token.id), Revoked
    )  # the new token is dead too


async def test_two_simultaneous_refreshes_of_one_token_rotate_exactly_once(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    first = await login(accounts, account.user_id)
    results = await asyncio.gather(*(rotate(accounts, first.id) for _ in range(10)))
    assert sum(isinstance(r, Rotated) for r in results) == 1
    assert sum(isinstance(r, AlreadyRefreshed) for r in results) == 9


async def test_refresh_is_refused_after_the_family_has_ended(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    token = await login(accounts, account.user_id, family_lifetime=timedelta(seconds=1))
    await asyncio.sleep(1.2)
    assert isinstance(await rotate(accounts, token.id), FamilyExpired)


async def test_a_token_past_its_own_lifetime_is_expired_while_its_family_lives(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    token = await login(accounts, account.user_id)
    await admin.run(
        "UPDATE refresh_tokens SET expires_at = now() - interval '1 second' WHERE id = :i",
        i=token.id,
    )
    assert isinstance(await rotate(accounts, token.id), Expired)


async def test_an_unknown_token_is_reported(accounts: PostgresAccountRepository) -> None:
    assert isinstance(await rotate(accounts, uuid.uuid4()), UnknownToken)


async def test_revoking_a_family_kills_its_tokens_and_can_be_repeated(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    token = await login(accounts, account.user_id)
    await accounts.revoke_token_family(token.family_id)
    await accounts.revoke_token_family(token.family_id)
    assert isinstance(await rotate(accounts, token.id), Revoked)


# --- membership


async def test_membership_is_per_organisation(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    one = await make_account()
    two = await make_account()
    assert await accounts.read_membership(user_id=one.user_id, organisation_id=one.organisation_id)
    assert (
        await accounts.read_membership(user_id=one.user_id, organisation_id=two.organisation_id)
        is None
    )


# --- API keys


async def new_key(
    accounts: PostgresAccountRepository,
    account: Account,
    prefix: str = "abc123",
    **kw: Any,
) -> CreateApiKeyResult:
    return await accounts.create_api_key(
        organisation_id=account.organisation_id,
        created_by_user_id=account.user_id,
        name=kw.get("name", "ci key"),
        key_prefix=prefix,
        key_hash=KEY_HASH,
        scopes=kw.get("scopes", ["jobs:read", "jobs:write"]),
        expires_at=kw.get("expires_at"),
    )


async def test_a_created_key_is_found_by_its_prefix(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    created = await new_key(accounts, account)
    assert isinstance(created, ApiKeyCreated)
    record = await accounts.find_api_key_by_prefix("abc123")
    assert record is not None
    assert record.id == created.id
    assert record.organisation_id == account.organisation_id
    assert record.key_hash == KEY_HASH
    assert record.scopes == ("jobs:read", "jobs:write")
    assert (record.revoked, record.expired, record.organisation_status) == (False, False, "active")
    assert await accounts.find_api_key_by_prefix("nope") is None


async def test_the_same_prefix_twice_is_reported_not_raised(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    await new_key(accounts, account, "dup001")
    assert isinstance(await new_key(accounts, account, "dup001"), PrefixTaken)


async def test_an_unknown_scope_is_refused_by_the_database(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    account = await make_account()
    with pytest.raises(IntegrityError):
        await new_key(accounts, account, "bad001", scopes=["job:write"])  # a typo


async def test_expiry_and_suspension_are_visible_to_authentication(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    await new_key(accounts, account, "exp001", expires_at=datetime.now(UTC) - timedelta(minutes=1))
    await new_key(accounts, account, "ok0001", expires_at=datetime.now(UTC) + timedelta(days=1))
    expired = await accounts.find_api_key_by_prefix("exp001")
    fine = await accounts.find_api_key_by_prefix("ok0001")
    assert expired is not None and expired.expired is True
    assert fine is not None and fine.expired is False
    await admin.run(
        "UPDATE organisations SET status = 'suspended' WHERE id = :i", i=account.organisation_id
    )
    suspended = await accounts.find_api_key_by_prefix("ok0001")
    assert suspended is not None and suspended.organisation_status == "suspended"


async def test_last_used_is_written_at_most_once_per_interval(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    account = await make_account()
    created = await new_key(accounts, account)
    assert isinstance(created, ApiKeyCreated)

    async def last_used() -> datetime | None:
        value: datetime | None = await admin.scalar(
            "SELECT last_used_at FROM api_keys WHERE id = :i", i=created.id
        )
        return value

    assert await last_used() is None
    await accounts.touch_api_key_last_used(created.id, timedelta(minutes=5))
    first = await last_used()
    assert first is not None
    await asyncio.sleep(0.05)
    await accounts.touch_api_key_last_used(created.id, timedelta(minutes=5))
    assert await last_used() == first  # inside the interval: unchanged
    await accounts.touch_api_key_last_used(created.id, timedelta(0))
    latest = await last_used()
    assert latest is not None
    assert latest > first  # interval over: written again


async def test_listing_is_per_organisation_without_hashes_and_includes_revoked_keys(
    accounts: PostgresAccountRepository, make_account: AccountFactory
) -> None:
    mine = await make_account()
    theirs = await make_account()
    first = await new_key(accounts, mine, "mine01", name="first")
    await new_key(accounts, mine, "mine02", name="second")
    await new_key(accounts, theirs, "their1", name="not mine")
    assert isinstance(first, ApiKeyCreated)
    await accounts.revoke_api_key(organisation_id=mine.organisation_id, key_id=first.id)
    listed = await accounts.list_api_keys(mine.organisation_id)
    assert [k.name for k in listed] == ["second", "first"]  # newest first
    assert [k.revoked_at is not None for k in listed] == [False, True]
    assert not hasattr(listed[0], "key_hash")
    assert len(await accounts.list_api_keys(mine.organisation_id, limit=1)) == 1


@pytest.mark.parametrize("limit", [0, -1, 501])
async def test_the_key_list_limit_is_checked(
    accounts: PostgresAccountRepository, limit: int
) -> None:
    with pytest.raises(ValueError, match="limit"):
        await accounts.list_api_keys(uuid.uuid4(), limit=limit)


async def test_revoking_is_per_organisation_and_can_be_repeated(
    accounts: PostgresAccountRepository, make_account: AccountFactory, admin: AdminSql
) -> None:
    mine = await make_account()
    other = await make_account()
    created = await new_key(accounts, mine)
    assert isinstance(created, ApiKeyCreated)
    assert (
        await accounts.revoke_api_key(organisation_id=other.organisation_id, key_id=created.id)
        is False
    )
    assert await admin.scalar("SELECT revoked_at FROM api_keys WHERE id = :i", i=created.id) is None
    assert (
        await accounts.revoke_api_key(organisation_id=mine.organisation_id, key_id=created.id)
        is True
    )
    first = await admin.scalar("SELECT revoked_at FROM api_keys WHERE id = :i", i=created.id)
    assert first is not None
    await asyncio.sleep(0.05)
    assert (
        await accounts.revoke_api_key(organisation_id=mine.organisation_id, key_id=created.id)
        is True
    )
    assert (
        await admin.scalar("SELECT revoked_at FROM api_keys WHERE id = :i", i=created.id) == first
    )
    record = await accounts.find_api_key_by_prefix("abc123")
    assert record is not None and record.revoked is True
