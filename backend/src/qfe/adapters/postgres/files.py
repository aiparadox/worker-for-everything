"""The ``files`` table: the record of uploaded inputs and stored results."""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from qfe.adapters.postgres.database import Database, seconds
from qfe.ports.repositories import FileKind, FileRecord

_COLUMNS = (
    "id, organisation_id, kind, storage_key, display_name, content_type, size_bytes, status, "
    "created_at, expires_at"
)


class PostgresFileRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create_file(
        self,
        *,
        organisation_id: uuid.UUID,
        kind: FileKind,
        storage_key: str,
        display_name: str,
        content_type: str,
        size_bytes: int,
        expires_in: timedelta | None,
    ) -> uuid.UUID:
        async with self._db.begin() as conn:
            file_id = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO files (organisation_id, kind, storage_key, display_name, "
                        "content_type, size_bytes, expires_at) "
                        "VALUES (:organisation_id, :kind, :storage_key, :display_name, "
                        ":content_type, :size_bytes, "
                        "CASE WHEN CAST(:expires_secs AS double precision) IS NULL THEN NULL "
                        "ELSE now() + "
                        "make_interval(secs => CAST(:expires_secs AS double precision)) "
                        "END) RETURNING id"
                    ),
                    {
                        "organisation_id": organisation_id,
                        "kind": kind.value,
                        "storage_key": storage_key,
                        "display_name": display_name,
                        "content_type": content_type,
                        "size_bytes": size_bytes,
                        "expires_secs": None if expires_in is None else seconds(expires_in),
                    },
                )
            ).scalar_one()
        return cast(uuid.UUID, file_id)

    async def get_file(
        self, *, organisation_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileRecord | None:
        async with self._db.begin() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        f"SELECT {_COLUMNS} FROM files "
                        "WHERE id = :id AND organisation_id = :organisation_id"
                    ),
                    {"id": file_id, "organisation_id": organisation_id},
                )
            ).first()
        if row is None:
            return None
        return FileRecord(
            id=row.id,
            organisation_id=row.organisation_id,
            kind=row.kind,
            storage_key=row.storage_key,
            display_name=row.display_name,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            status=row.status,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )

    async def mark_files_available(
        self, *, organisation_id: uuid.UUID, file_ids: Sequence[uuid.UUID]
    ) -> list[uuid.UUID]:
        if not file_ids:
            return []
        statement = sa.text(
            "UPDATE files SET status = 'available', expires_at = NULL "
            "WHERE organisation_id = :organisation_id AND id = ANY(:ids) RETURNING id"
        ).bindparams(sa.bindparam("ids", type_=postgresql.ARRAY(sa.Uuid)))
        async with self._db.begin() as conn:
            rows = (
                await conn.execute(
                    statement, {"organisation_id": organisation_id, "ids": list(file_ids)}
                )
            ).all()
        return [row.id for row in rows]
