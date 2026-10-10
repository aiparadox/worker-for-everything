#!/bin/bash
# Creates the two database roles and prepares the database on the first start of an empty data
# folder (docs/specs/FEAT-20261010-1204-alembic-schema.md, section 3.2).
#
#   qfe_migrator  owns the database objects and can change the schema; only the migrate job uses it.
#   qfe_app       reads and writes rows only; the api, worker, relay and maintenance use it.
#
# The image runs this once, when the data folder is empty. It is written so that running it again
# changes nothing harmful. Passwords come from the environment, never from the repository.
#
# QFE_TEMPLATE_DB (optional, used by the test services only): also prepare an empty database with
# this name and mark it as a template, so tests can clone a fresh database from it in milliseconds.
set -euo pipefail

: "${QFE_APP_DB_PASSWORD:?QFE_APP_DB_PASSWORD is required}"
: "${QFE_MIGRATOR_DB_PASSWORD:?QFE_MIGRATOR_DB_PASSWORD is required}"

# Roles belong to the whole server, so they are created once.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$QFE_APP_DB_PASSWORD" \
  -v migrator_password="$QFE_MIGRATOR_DB_PASSWORD" <<'SQL'
-- Create each role only if it does not exist yet (\gexec runs the text the query returns).
SELECT format('CREATE ROLE qfe_migrator LOGIN PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qfe_migrator')
\gexec

SELECT format('CREATE ROLE qfe_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qfe_app')
\gexec
SQL

# Privileges belong to one database, so they are set in each database that is prepared.
prepare_database() {
  local db_name="$1"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db_name" -v db_name="$db_name" <<'SQL'
-- The migrator owns the database and the public schema, so it can create tables there.
ALTER DATABASE :"db_name" OWNER TO qfe_migrator;
ALTER SCHEMA public OWNER TO qfe_migrator;

-- Nobody else may create objects in the public schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO qfe_app;

-- Every table the migrator creates from now on is readable and writable by the app role,
-- and the app role cannot change the schema.
ALTER DEFAULT PRIVILEGES FOR ROLE qfe_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO qfe_app;
ALTER DEFAULT PRIVILEGES FOR ROLE qfe_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO qfe_app;
SQL
}

prepare_database "$POSTGRES_DB"

if [ -n "${QFE_TEMPLATE_DB:-}" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v template_db="$QFE_TEMPLATE_DB" <<'SQL'
SELECT format('CREATE DATABASE %I', :'template_db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'template_db')
\gexec
SQL
  prepare_database "$QFE_TEMPLATE_DB"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -c "ALTER DATABASE \"$QFE_TEMPLATE_DB\" WITH IS_TEMPLATE true"
fi
