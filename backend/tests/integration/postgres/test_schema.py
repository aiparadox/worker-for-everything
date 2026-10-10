"""The schema built by the migrations does what docs/DATABASE.md says
(docs/specs/FEAT-20261010-1204-alembic-schema.md, section 4)."""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.integration.postgres.conftest import Database

TABLES = {
    "organisations",
    "users",
    "auth_identities",
    "refresh_tokens",
    "memberships",
    "api_keys",
    "files",
    "job_files",
    "jobs",
    "job_attempts",
    "outbox",
}
HEAD_REVISION_COUNT = 1


async def _scalar(engine: AsyncEngine, sql: str, **params: object) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql), params)).scalar_one()


async def _insert_organisation(engine: AsyncEngine, slug: str = "acme") -> uuid.UUID:
    async with engine.begin() as connection:
        result = await connection.execute(
            text("INSERT INTO organisations (name, slug) VALUES ('Acme', :slug) RETURNING id"),
            {"slug": slug},
        )
        value = result.scalar_one()
        assert isinstance(value, uuid.UUID)
        return value


async def _insert_job(
    engine: AsyncEngine, organisation_id: uuid.UUID, **overrides: object
) -> uuid.UUID:
    values: dict[str, object] = {
        "org": organisation_id,
        "status": "queued",
        "trace": "0" * 32,
        "key": None,
    }
    values.update(overrides)
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                "INSERT INTO jobs (organisation_id, type, type_version, status, payload, "
                "max_attempts, trace_id, idempotency_key) "
                "VALUES (:org, 'echo', '1', :status, '{}', 3, :trace, :key) RETURNING id"
            ),
            values,
        )
        value = result.scalar_one()
        assert isinstance(value, uuid.UUID)
        return value


async def test_upgrade_creates_all_tables_and_repeating_it_changes_nothing(
    migrated_database: Database, app_engine: AsyncEngine
) -> None:
    async with app_engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = {row[0] for row in rows}
    assert names == TABLES | {"alembic_version"}

    again = migrated_database.run_alembic("upgrade", "head")
    assert again.returncode == 0, again.stderr
    current = migrated_database.run_alembic("current")
    assert "(head)" in current.stdout + current.stderr


async def test_alembic_check_finds_no_difference_between_tables_and_migrations(
    migrated_database: Database,
) -> None:
    result = migrated_database.run_alembic("check")
    assert result.returncode == 0, result.stdout + result.stderr


async def test_two_migrations_started_together_end_correctly(empty_database: Database) -> None:
    first, second = await asyncio.gather(
        asyncio.to_thread(empty_database.run_alembic, "upgrade", "head"),
        asyncio.to_thread(empty_database.run_alembic, "upgrade", "head"),
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    engine = create_async_engine(empty_database.migrator_url)
    try:
        assert await _scalar(engine, "SELECT count(*) FROM alembic_version") == HEAD_REVISION_COUNT
        assert await _scalar(
            engine, "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
        ) == (len(TABLES) + 1)
    finally:
        await engine.dispose()


async def test_ids_are_generated_by_uuidv7(app_engine: AsyncEngine) -> None:
    organisation_id = await _insert_organisation(app_engine)
    assert organisation_id.version == 7
    seconds = await _scalar(
        app_engine,
        "SELECT abs(extract(epoch FROM (now() - uuid_extract_timestamp(:id))))",
        id=organisation_id,
    )
    assert isinstance(seconds, int | float) or float(str(seconds)) < 60  # created just now
    assert float(str(seconds)) < 60


async def test_app_role_can_use_rows_but_cannot_change_the_schema(
    app_engine: AsyncEngine,
) -> None:
    organisation_id = await _insert_organisation(app_engine)
    async with app_engine.begin() as connection:
        await connection.execute(
            text("UPDATE organisations SET name = 'Acme 2' WHERE id = :id"), {"id": organisation_id}
        )
        await connection.execute(
            text("DELETE FROM organisations WHERE id = :id"), {"id": organisation_id}
        )
    for statement in (
        "CREATE TABLE intruder (id int)",
        "ALTER TABLE organisations ADD COLUMN extra int",
        "DROP TABLE organisations",
    ):
        with pytest.raises(ProgrammingError):
            async with app_engine.begin() as connection:
                await connection.execute(text(statement))


async def test_migrator_role_can_change_the_schema(migrator_engine: AsyncEngine) -> None:
    async with migrator_engine.begin() as connection:
        await connection.execute(text("CREATE TABLE scratch (id int)"))
        await connection.execute(text("DROP TABLE scratch"))


@pytest.mark.parametrize(
    "bad_status", ["", "done", "QUEUED", "canceled"]
)  # canceled (one l) is not the allowed spelling
async def test_a_job_status_outside_the_list_is_rejected(
    app_engine: AsyncEngine, bad_status: str
) -> None:
    organisation_id = await _insert_organisation(app_engine)
    with pytest.raises(IntegrityError):
        await _insert_job(app_engine, organisation_id, status=bad_status)


async def test_every_allowed_job_status_is_accepted(app_engine: AsyncEngine) -> None:
    organisation_id = await _insert_organisation(app_engine)
    for status in ("queued", "running", "retrying", "succeeded", "failed", "cancelled"):
        await _insert_job(app_engine, organisation_id, status=status)


async def test_other_checks_reject_bad_values(app_engine: AsyncEngine) -> None:
    organisation_id = await _insert_organisation(app_engine)
    bad_statements = [
        "INSERT INTO organisations (name, slug) VALUES ('X', 'Not Lower')",
        "INSERT INTO organisations (name, slug, status) VALUES ('X', 'x1', 'gone')",
        "INSERT INTO users (email, status) VALUES ('a@b.co', 'sleeping')",
        "INSERT INTO files (organisation_id, kind, storage_key, display_name, content_type, "
        f"size_bytes) VALUES ('{organisation_id}', 'other', 'k1', 'f', 'text/plain', 1)",
        "INSERT INTO files (organisation_id, kind, storage_key, display_name, content_type, "
        f"size_bytes) VALUES ('{organisation_id}', 'input', 'k2', 'f', 'text/plain', -1)",
        "INSERT INTO api_keys (organisation_id, name, key_prefix, key_hash, scopes) "
        f"VALUES ('{organisation_id}', 'k', 'p1', '\\x00', ARRAY['job:write'])",
    ]
    for statement in bad_statements:
        with pytest.raises(IntegrityError):
            async with app_engine.begin() as connection:
                await connection.execute(text(statement))


async def test_outbox_reason_and_attempt_outcome_checks(app_engine: AsyncEngine) -> None:
    organisation_id = await _insert_organisation(app_engine)
    job_id = await _insert_job(app_engine, organisation_id)
    with pytest.raises(IntegrityError):
        async with app_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO outbox (job_id, routing_key, reason, headers, body) "
                    "VALUES (:job, 'echo', 'because', '{}', '{}')"
                ),
                {"job": job_id},
            )
    with pytest.raises(IntegrityError):
        async with app_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO job_attempts (job_id, attempt_number, started_at, outcome) "
                    "VALUES (:job, 1, now(), 'exploded')"
                ),
                {"job": job_id},
            )


async def test_foreign_key_to_a_missing_parent_is_rejected(app_engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError):
        await _insert_job(app_engine, uuid.uuid4())


async def test_idempotency_key_is_unique_per_organisation_only(app_engine: AsyncEngine) -> None:
    first = await _insert_organisation(app_engine, "first")
    second = await _insert_organisation(app_engine, "second")
    await _insert_job(app_engine, first, key="same-key")
    await _insert_job(app_engine, second, key="same-key")  # another organisation: allowed
    await _insert_job(app_engine, first)  # no key: any number allowed
    await _insert_job(app_engine, first)
    with pytest.raises(IntegrityError):
        await _insert_job(app_engine, first, key="same-key")


async def test_email_is_unique_ignoring_case(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as connection:
        await connection.execute(text("INSERT INTO users (email) VALUES ('Person@Example.com')"))
    with pytest.raises(IntegrityError):
        async with app_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (email) VALUES ('person@example.com')")
            )


async def test_a_file_that_a_job_uses_cannot_be_deleted(app_engine: AsyncEngine) -> None:
    organisation_id = await _insert_organisation(app_engine)
    job_id = await _insert_job(app_engine, organisation_id)
    async with app_engine.begin() as connection:
        file_id = (
            await connection.execute(
                text(
                    "INSERT INTO files (organisation_id, kind, storage_key, display_name, "
                    "content_type, size_bytes) "
                    "VALUES (:org, 'input', 'orgs/x/1', 'a.txt', 'text/plain', 3) RETURNING id"
                ),
                {"org": organisation_id},
            )
        ).scalar_one()
        await connection.execute(
            text("INSERT INTO job_files (job_id, file_id) VALUES (:job, :file)"),
            {"job": job_id, "file": file_id},
        )
    with pytest.raises(IntegrityError):
        async with app_engine.begin() as connection:
            await connection.execute(text("DELETE FROM files WHERE id = :id"), {"id": file_id})


async def test_table_settings_are_applied(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT relname, reloptions FROM pg_class "
                "WHERE relname IN ('jobs', 'job_attempts', 'outbox') ORDER BY relname"
            )
        )
        options = {name: dict(item.split("=") for item in (opts or [])) for name, opts in rows}
    assert options["jobs"]["fillfactor"] == "80"
    for table in ("jobs", "job_attempts", "outbox"):
        assert options[table]["autovacuum_vacuum_scale_factor"] == "0.02"
        assert options[table]["autovacuum_vacuum_threshold"] == "1000"
        assert options[table]["autovacuum_analyze_scale_factor"] == "0.01"


# --- Conventions from DATABASE.md section 2, checked over every table at once ---------------


async def test_every_table_with_an_id_uses_uuidv7_and_created_at(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT table_name, column_name, data_type, column_default "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name <> 'alembic_version'"
            )
        )
        columns = {(row[0], row[1]): (row[2], row[3]) for row in rows}
    for table in TABLES - {"memberships", "job_files"}:
        data_type, default = columns[(table, "id")]
        assert data_type == "uuid", table
        assert default == "uuidv7()", table
    for table in TABLES - {"job_files", "job_attempts"}:
        assert ("created_at" in {c for (t, c) in columns if t == table}) or table == "outbox", table


async def test_no_column_uses_time_without_time_zone(app_engine: AsyncEngine) -> None:
    count = await _scalar(
        app_engine,
        "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' "
        "AND data_type = 'timestamp without time zone'",
    )
    assert count == 0


async def test_every_foreign_key_column_starts_an_index(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as connection:
        rows = await connection.execute(
            text(
                """
                SELECT c.conrelid::regclass::text AS table_name, c.conname
                FROM pg_constraint c
                WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
                  AND NOT EXISTS (
                    SELECT 1 FROM pg_index i
                    WHERE i.indrelid = c.conrelid
                      AND array_to_string((i.indkey::int2[])[0:cardinality(c.conkey) - 1], ',')
                          = array_to_string(c.conkey, ',')
                  )
                """
            )
        )
        unindexed = [tuple(row) for row in rows]
    assert unindexed == []


async def test_a_wrong_connection_is_refused(empty_database: Database) -> None:
    bad = create_async_engine(
        empty_database.server.url("qfe_app", "wrong-password", empty_database.name)
    )
    try:
        with pytest.raises(DBAPIError):
            async with bad.connect():
                pass
    finally:
        await bad.dispose()
