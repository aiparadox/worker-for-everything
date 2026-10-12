"""Accounts: users, organisations, memberships, refresh tokens and API keys.

Spec: docs/specs/FEAT-20261010-1211-data-access.md. Every statement that compares with "now" uses
the database clock.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from qfe.adapters.postgres.database import Database, constraint_name, seconds
from qfe.ports.repositories import (
    AlreadyRefreshed,
    ApiKeyCreated,
    ApiKeyRecord,
    ApiKeySummary,
    CreateApiKeyResult,
    CreateUserResult,
    EmailTaken,
    Expired,
    FamilyExpired,
    Membership,
    NewRefreshToken,
    PasswordIdentity,
    PrefixTaken,
    ReuseDetected,
    Revoked,
    Rotated,
    RotateResult,
    SlugTaken,
    UnknownToken,
    UserCreated,
)

MAX_KEY_LIST = 500
_EMAIL_INDEX = "uq_users_email_lower"
_SLUG_CONSTRAINT = "uq_organisations_slug"
_PREFIX_CONSTRAINT = "uq_api_keys_key_prefix"


class PostgresAccountRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create_user_with_organisation(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str | None,
        organisation_name: str,
        organisation_slug: str,
    ) -> CreateUserResult:
        try:
            async with self._db.begin() as conn:
                user_id = (
                    await conn.execute(
                        sa.text(
                            "INSERT INTO users (email, display_name) "
                            "VALUES (:email, :display_name) RETURNING id"
                        ),
                        {"email": email, "display_name": display_name},
                    )
                ).scalar_one()
                await conn.execute(
                    sa.text(
                        "INSERT INTO auth_identities "
                        "(user_id, provider, provider_subject, secret_hash) "
                        "VALUES (:user_id, 'password', :subject, :secret_hash)"
                    ),
                    {"user_id": user_id, "subject": str(user_id), "secret_hash": password_hash},
                )
                organisation_id = (
                    await conn.execute(
                        sa.text(
                            "INSERT INTO organisations (name, slug) "
                            "VALUES (:name, :slug) RETURNING id"
                        ),
                        {"name": organisation_name, "slug": organisation_slug},
                    )
                ).scalar_one()
                await conn.execute(
                    sa.text(
                        "INSERT INTO memberships (organisation_id, user_id, role) "
                        "VALUES (:organisation_id, :user_id, 'owner')"
                    ),
                    {"organisation_id": organisation_id, "user_id": user_id},
                )
        except IntegrityError as error:
            broken = constraint_name(error)
            if broken == _EMAIL_INDEX:
                return EmailTaken()
            if broken == _SLUG_CONSTRAINT:
                return SlugTaken()
            raise
        return UserCreated(user_id=user_id, organisation_id=organisation_id)

    async def find_password_identity(self, email: str) -> PasswordIdentity | None:
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT u.id, u.status, i.secret_hash FROM users u "
                        "JOIN auth_identities i ON i.user_id = u.id AND i.provider = 'password' "
                        "WHERE lower(u.email) = lower(:email)"
                    ),
                    {"email": email},
                )
            ).first()
        if row is None:
            return None
        return PasswordIdentity(user_id=row.id, user_status=row.status, secret_hash=row.secret_hash)

    async def record_login(self, user_id: uuid.UUID) -> None:
        async with self._db.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE users SET last_login_at = now(), updated_at = now() WHERE id = :id"
                ),
                {"id": user_id},
            )

    async def start_login_session(
        self,
        *,
        user_id: uuid.UUID,
        token_lifetime: timedelta,
        family_lifetime: timedelta,
        ip: str | None,
        user_agent: str | None,
    ) -> NewRefreshToken:
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO refresh_tokens "
                        "(family_id, user_id, expires_at, family_expires_at, ip, user_agent) "
                        "VALUES (uuidv7(), :user_id, "
                        "least(now() + make_interval(secs => :token_secs), "
                        "      now() + make_interval(secs => :family_secs)), "
                        "now() + make_interval(secs => :family_secs), :ip, :user_agent) "
                        "RETURNING id, family_id, user_id, expires_at, family_expires_at"
                    ),
                    {
                        "user_id": user_id,
                        "token_secs": seconds(token_lifetime),
                        "family_secs": seconds(family_lifetime),
                        "ip": ip,
                        "user_agent": user_agent,
                    },
                )
            ).one()
        return _token(row)

    async def rotate_refresh_token(
        self,
        *,
        presented_id: uuid.UUID,
        reuse_window: timedelta,
        token_lifetime: timedelta,
        ip: str | None,
        user_agent: str | None,
    ) -> RotateResult:
        async with self._db.begin() as conn:
            # The presented row is locked, so two simultaneous refreshes of one token are
            # serialised: exactly one rotates and the other lands in the reuse window.
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT id, family_id, user_id, family_expires_at, used_at, "
                        "  revoked_at IS NOT NULL AS revoked, "
                        "  expires_at <= now() AS token_expired, "
                        "  family_expires_at <= now() AS family_expired, "
                        "  (used_at IS NOT NULL AND "
                        "   now() - used_at <= make_interval(secs => :window)) AS within_window "
                        "FROM refresh_tokens WHERE id = :id FOR UPDATE"
                    ),
                    {"id": presented_id, "window": seconds(reuse_window)},
                )
            ).first()
            if row is None:
                return UnknownToken()
            if row.revoked:
                return Revoked()
            # The family is checked before the token's own expiry: a token never outlives its
            # family, so the other order could never report that the whole login has ended.
            if row.family_expired:
                return FamilyExpired()
            if row.token_expired:
                return Expired()
            if row.used_at is not None:
                if row.within_window:
                    return AlreadyRefreshed()
                await _revoke_family(conn, row.family_id)
                return ReuseDetected()
            new = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO refresh_tokens "
                        "(family_id, user_id, expires_at, family_expires_at, ip, user_agent) "
                        "VALUES (:family_id, :user_id, "
                        "least(now() + make_interval(secs => :token_secs), :family_expires_at), "
                        ":family_expires_at, :ip, :user_agent) "
                        "RETURNING id, family_id, user_id, expires_at, family_expires_at"
                    ),
                    {
                        "family_id": row.family_id,
                        "user_id": row.user_id,
                        "token_secs": seconds(token_lifetime),
                        "family_expires_at": row.family_expires_at,
                        "ip": ip,
                        "user_agent": user_agent,
                    },
                )
            ).one()
            await conn.execute(
                sa.text(
                    "UPDATE refresh_tokens SET used_at = now(), replaced_by = :new_id "
                    "WHERE id = :id"
                ),
                {"new_id": new.id, "id": presented_id},
            )
        return Rotated(_token(new))

    async def revoke_token_family(self, family_id: uuid.UUID) -> None:
        async with self._db.begin() as conn:
            await _revoke_family(conn, family_id)

    async def read_membership(
        self, *, user_id: uuid.UUID, organisation_id: uuid.UUID
    ) -> Membership | None:
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT m.role, u.status AS user_status, o.status AS organisation_status "
                        "FROM memberships m "
                        "JOIN users u ON u.id = m.user_id "
                        "JOIN organisations o ON o.id = m.organisation_id "
                        "WHERE m.user_id = :user_id AND m.organisation_id = :organisation_id"
                    ),
                    {"user_id": user_id, "organisation_id": organisation_id},
                )
            ).first()
        if row is None:
            return None
        return Membership(
            role=row.role,
            user_status=row.user_status,
            organisation_status=row.organisation_status,
        )

    async def create_api_key(
        self,
        *,
        organisation_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        name: str,
        key_prefix: str,
        key_hash: bytes,
        scopes: Sequence[str],
        expires_at: datetime | None,
    ) -> CreateApiKeyResult:
        statement = sa.text(
            "INSERT INTO api_keys "
            "(organisation_id, created_by_user_id, name, key_prefix, key_hash, scopes, expires_at) "
            "VALUES (:organisation_id, :created_by_user_id, :name, :key_prefix, :key_hash, "
            ":scopes, :expires_at) RETURNING id, created_at"
        ).bindparams(sa.bindparam("scopes", type_=postgresql.ARRAY(sa.Text)))
        try:
            async with self._db.begin() as conn:
                row = (
                    await conn.execute(
                        statement,
                        {
                            "organisation_id": organisation_id,
                            "created_by_user_id": created_by_user_id,
                            "name": name,
                            "key_prefix": key_prefix,
                            "key_hash": key_hash,
                            "scopes": list(scopes),
                            "expires_at": expires_at,
                        },
                    )
                ).one()
        except IntegrityError as error:
            if constraint_name(error) == _PREFIX_CONSTRAINT:
                return PrefixTaken()
            raise
        return ApiKeyCreated(id=row.id, created_at=row.created_at)

    async def find_api_key_by_prefix(self, key_prefix: str) -> ApiKeyRecord | None:
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT k.id, k.organisation_id, k.key_hash, k.scopes, k.last_used_at, "
                        "  k.revoked_at IS NOT NULL AS revoked, "
                        "  (k.expires_at IS NOT NULL AND k.expires_at <= now()) AS expired, "
                        "  o.status AS organisation_status "
                        "FROM api_keys k JOIN organisations o ON o.id = k.organisation_id "
                        "WHERE k.key_prefix = :prefix"
                    ),
                    {"prefix": key_prefix},
                )
            ).first()
        if row is None:
            return None
        return ApiKeyRecord(
            id=row.id,
            organisation_id=row.organisation_id,
            key_hash=bytes(row.key_hash),
            scopes=tuple(row.scopes),
            revoked=row.revoked,
            expired=row.expired,
            organisation_status=row.organisation_status,
            last_used_at=row.last_used_at,
        )

    async def touch_api_key_last_used(self, key_id: uuid.UUID, min_interval: timedelta) -> None:
        async with self._db.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE api_keys SET last_used_at = now() WHERE id = :id AND "
                    "(last_used_at IS NULL OR "
                    " last_used_at < now() - make_interval(secs => :interval))"
                ),
                {"id": key_id, "interval": seconds(min_interval)},
            )

    async def list_api_keys(
        self, organisation_id: uuid.UUID, limit: int = 100
    ) -> list[ApiKeySummary]:
        if not 1 <= limit <= MAX_KEY_LIST:
            raise ValueError(f"limit must be between 1 and {MAX_KEY_LIST}")
        async with self._db.begin() as conn:
            rows = (
                await conn.execute(
                    sa.text(
                        "SELECT id, name, key_prefix, scopes, created_by_user_id, created_at, "
                        "last_used_at, expires_at, revoked_at FROM api_keys "
                        "WHERE organisation_id = :organisation_id ORDER BY id DESC LIMIT :limit"
                    ),
                    {"organisation_id": organisation_id, "limit": limit},
                )
            ).all()
        return [
            ApiKeySummary(
                id=row.id,
                name=row.name,
                key_prefix=row.key_prefix,
                scopes=tuple(row.scopes),
                created_by_user_id=row.created_by_user_id,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]

    async def revoke_api_key(self, *, organisation_id: uuid.UUID, key_id: uuid.UUID) -> bool:
        async with self._db.begin() as conn:
            found = (
                await conn.execute(
                    sa.text(
                        "UPDATE api_keys SET revoked_at = coalesce(revoked_at, now()) "
                        "WHERE id = :id AND organisation_id = :organisation_id RETURNING id"
                    ),
                    {"id": key_id, "organisation_id": organisation_id},
                )
            ).first()
        return found is not None


async def _revoke_family(conn: AsyncConnection, family_id: uuid.UUID) -> None:
    await conn.execute(
        sa.text(
            "UPDATE refresh_tokens SET revoked_at = now() "
            "WHERE family_id = :family_id AND revoked_at IS NULL"
        ),
        {"family_id": family_id},
    )


def _token(row: Any) -> NewRefreshToken:
    return NewRefreshToken(
        id=row.id,
        family_id=row.family_id,
        user_id=row.user_id,
        expires_at=row.expires_at,
        family_expires_at=row.family_expires_at,
    )
