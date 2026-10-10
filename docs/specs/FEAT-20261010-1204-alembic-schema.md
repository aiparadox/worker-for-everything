# FEAT-20261010-1204: Alembic and the first database schema

Status: **approved by the user on 2026-10-10** (all questions in the last section answered yes; recommendations accepted as written). Working branch: `feat-20261010-1204-alembic-schema`, from `master` after `FEAT-1202`. Depends on: `FEAT-20261010-1202` (Postgres service), `FEAT-20261010-1203` (config), `FEAT-20261010-1208` (packages). Settles D46 by trial.

## 1. What this builds and why

The real database: the 11 tables in `docs/DATABASE.md`, the three database roles, the one-shot `migrate` container, and proof that the schema does what the design says. It is also the first real test of SQLAlchemy 2.1 with asyncpg and Alembic, which were only checked from package metadata (D46; fallback 2.0.54).

## 2. Verified facts

- `DATABASE.md` section 4 lists the tables (organisations, users, auth_identities, refresh_tokens, memberships, api_keys, files, job_files, jobs, job_attempts, outbox), section 2 the conventions (uuidv7 default, `timestamptz`, text plus CHECK for statuses, hashes as `bytea`), section 9 the roles and table settings, section 12 the migration rules.
- Postgres 18 has `uuidv7()` built in (official docs, notepad). The docs do not promise ordering inside one millisecond, so nothing may depend on it.
- `platform.md` records two gaps this spec closes: who creates the roles and database at first start (PLT-03), and what stops two migrations running at once (PLT-08).
- Alembic 1.20.0 needs SQLAlchemy 2.0 or newer, and its changelog says 1.19.2 added support for SQLAlchemy 2.1 accessors (notepad, read from the changelog); that is not the same as a tested full match. **Not verified:** that the async template, `alembic check` and the `uuidv7()` default work with SQLAlchemy 2.1.4 and asyncpg 0.32.0 on Python 3.12. This task finds out.

## 3. Proposal

### 3.1 Alembic setup

Created with Alembic's own generator (`alembic init`, with the async template if `alembic list_templates` shows one; Module 8), in `backend/migrations/`. The database URL comes from `MigrateSettings` (`FEAT-1203`), never from `alembic.ini`. File names carry the date so they sort.

### 3.2 Roles and database creation (closes PLT-03)

A shell script in `deploy/postgres/init/`, run by the Postgres image on the **first** start of an empty data volume:

- creates `qfe_migrator` (can change the schema, owns the objects) and `qfe_app` (read and write rows only, no schema changes); `qfe_readonly` for dashboards is left out until a dashboard needs it;
- takes both passwords from environment variables, so no password is in the repository;
- sets default privileges so every table `qfe_migrator` creates is automatically readable and writable by `qfe_app`.

Known limit, stated so nobody is surprised: the image runs init scripts only when the data folder is empty. After the first start, changing a password in `.env` does not change it in the database. In development the fix is `docker compose down -v` (it deletes the data). Production role management is part of the deferred production work (`WISH-20261010-1309`).

### 3.3 Schema as code, then migrations

- The tables are written once as SQLAlchemy Core table definitions in `qfe/adapters/postgres/tables.py`. This is the code form of `DATABASE.md`; `FEAT-1211` builds the repositories on it. (Core, not ORM classes, because the design keeps all SQL in the postgres adapter and uses explicit transactional operations; the repository spec can still revisit this.)
- Migrations are **generated** with `alembic revision --autogenerate`, then reviewed and edited by hand (`DATABASE.md` section 12), because autogenerate cannot express: `DEFAULT uuidv7()`, partial indexes, `fillfactor`, autovacuum settings and some CHECK details.
- Three migrations, one per logical group (the rule is one migration per logical change): (1) accounts and auth: organisations, users, auth_identities, memberships, refresh_tokens, api_keys; (2) files; (3) jobs: jobs, job_attempts, job_files, outbox, including `fillfactor = 80` on `jobs` and lowered autovacuum thresholds on `jobs`, `job_attempts` and `outbox`. The exact autovacuum numbers are chosen from the Postgres documentation at the start of the work and written into `DATABASE.md`.
- **Two migrations never run at once (closes PLT-08):** the migration environment takes a Postgres advisory lock for the whole run, on the migrator's direct connection. A second `migrate` waits.

### 3.4 The `migrate` container

Added to `compose.yaml` here: same backend image, command `alembic upgrade head`, connects as `qfe_migrator`, exits when done. Services that need tables use `depends_on: condition: service_completed_successfully`. If it fails, the stack does not come up.

## 4. Tests (integration, against the Compose test profile, D48)

- `upgrade head` on an empty database creates all 11 tables; running it again changes nothing.
- `alembic check` reports no difference between `tables.py` and the migrations (so the two cannot drift).
- `uuidv7()` default produces a valid UUID and `uuid_extract_timestamp` returns a time near now.
- A status outside the allowed list is rejected by the CHECK on `jobs`, `files` and `outbox`; a row pointing to a missing parent is rejected by the foreign key; the unique rule `(organisation_id, idempotency_key)` holds.
- `qfe_app` can insert, update, delete and select, and **cannot** create, alter or drop a table.
- `fillfactor` on `jobs` and the autovacuum settings are present (read from `pg_class.reloptions`).
- Two `migrate` runs started together end with a correct schema and no error.
- Result recorded: SQLAlchemy 2.1.4 plus asyncpg plus Alembic worked, or the fallback decision.

## 5. Check for the same problem elsewhere

Lateral: every table, not only the big ones, gets the same convention checks (key default, `timestamptz`, indexed foreign keys, CHECK on status columns), run as one loop over the schema rather than table by table, so a missed index shows up. Causal depth: schema drift has two causes, someone editing `tables.py` without a migration (caught by `alembic check`) and someone editing a migration without the table definition (caught by the same check). Any difference between `DATABASE.md` and what is built is fixed in the document in the same commit, as `DATABASE.md` section 12 requires.

## 6. Out of scope

Repositories and transactional operations (`FEAT-1211`); the advisory lock for the active-jobs cap (a use of the database, built in `FEAT-1211`); PgBouncer and its lock test (`WISH-20261010-1310`); down-migrations (A9); partitioning.

## 7. Questions for you

1. Core table definitions as the code form of the schema, plus autogenerate and `alembic check` (my recommendation), or hand-written migrations only?
2. Three migrations instead of one, as in 3.3?
