# Specs

One short spec per `TODO.md` item (CLAUDE.md Module 7): what is built, the facts checked, the proposal, tests, and the branch. A spec is a draft until the user approves it; no code is written before that.

## Phase 0 specs (written 2026-10-10, draft for approval)

Order of work. Each task gets its own branch from `master` and is merged back to `master` before the next one starts (the process agreed on 2026-10-10).

| Order | Item | Spec | Branch |
|---|---|---|---|
| 1 | FEAT-20261010-1201 | [repository layout](FEAT-20261010-1201-repo-layout.md) | `feat-20261010-1201-repo-layout` |
| 2 | FEAT-20261010-1208 | [dependencies](FEAT-20261010-1208-dependencies.md) | `feat-20261010-1208-dependencies` |
| 3 | FEAT-20261010-1203 | [configuration](FEAT-20261010-1203-config.md) | `feat-20261010-1203-config` |
| 4 | FEAT-20261010-1202 | [Docker Compose](FEAT-20261010-1202-compose.md) | `feat-20261010-1202-compose` |
| 5 | FEAT-20261010-1204 | [Alembic and schema](FEAT-20261010-1204-alembic-schema.md) | `feat-20261010-1204-alembic-schema` |
| 6 | FEAT-20261010-1205 | [observability skeleton](FEAT-20261010-1205-observability-skeleton.md) | `feat-20261010-1205-observability-skeleton` |
| 7 | FEAT-20261010-1206 | [ports and contract tests](FEAT-20261010-1206-ports-and-contract-tests.md) | `feat-20261010-1206-ports` |
| 8 | FEAT-20261010-1207 | [test scaffolding and docs check](FEAT-20261010-1207-test-scaffolding.md) | `feat-20261010-1207-test-scaffolding` |
| 9 | FEAT-20261010-1209 | [SeaweedFS checks](FEAT-20261010-1209-seaweedfs-checks.md) | `feat-20261010-1209-seaweedfs-checks` |

The order follows the dependencies: the dependency install (1208) comes right after the layout because the config, Compose and test tasks all need the packages; the real-service trials (SQLAlchemy 2.1 with asyncpg, the `redis` client with Valkey, boto3 with SeaweedFS) come with the tasks that first have a running service.
