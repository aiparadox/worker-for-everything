# FEAT-20261010-1207: test scaffolding and the API docs check

Status: **approved by the user on 2026-10-10** (all questions in the last section answered yes; recommendations accepted as written). Working branch: `feat-20261010-1207-test-scaffolding`, from `master` after `FEAT-1206`. Depends on: `FEAT-20261010-1202`, `FEAT-20261010-1204`, `FEAT-20261010-1205`, `FEAT-20261010-1206`.

## 1. What this builds and why

The shared machinery every later task writes tests with: how the four test levels are run, the fixtures that give integration tests a clean database, queue and storage, an end-to-end smoke test, and the check that fails when an API route has no documentation file (`ARCHITECTURE.md` sections 13 and 14).

## 2. Verified facts

- Levels (`ARCHITECTURE.md` section 13): unit (in-memory fakes, no Docker), integration (each adapter against the real service), contract (one suite per port, run against every adapter), end to end (full flows through Compose), plus a docs check.
- D48: integration, contract-against-real-adapters and end-to-end tests use the Compose **test profile** (`FEAT-1202`), not testcontainers.
- Rule for docs (`ARCHITECTURE.md` section 14): one file per endpoint in `docs/apis/<endpoint>.md` covering method, path, path and query parameters, headers, request body, responses, errors, auth, scopes and rate limits, with examples; `docs/apis/README.md` is the short index; the check fails the build when an endpoint has no file.
- Gap found: the design names a CI check but **no task builds the CI workflow**. See section 6.

## 3. Proposal

### 3.1 Running the levels

| Command (from `backend/`) | Runs | Needs Docker |
|---|---|---|
| `uv run pytest tests/unit tests/contract` | unit tests and the contract suites against the fakes | no |
| `uv run pytest tests/integration` | adapters and database against the test profile | yes |
| `uv run pytest tests/e2e` | flows against the whole stack | yes |

Markers (`unit`, `integration`, `contract`, `e2e`) are set from the folder, so nobody has to remember to tag a test. Strictness: unknown markers are errors.

### 3.2 No silent skipping

Integration and end-to-end tests **fail with a clear message** ("test services are not running; start them with `docker compose --profile test up -d --wait`") when a service is unreachable. They are never skipped quietly, because a silently skipped test looks like a pass (CLAUDE.md Module 4 in spirit).

### 3.3 Fixtures

- **Endpoints** come from `.env.test` (`FEAT-1202`), parsed with the same settings classes as the app.
- **Database:** migrations are applied once per test run to the test database (as `qfe_migrator`). Between tests, all tables are emptied with one `TRUNCATE ... CASCADE`. Chosen over cloning a template database because the data is tiny and it is simpler; revisit if the suite gets slow. Tests connect as `qfe_app`, like the real services.
- **RabbitMQ, Valkey, storage:** every run uses a unique name prefix (queue names, key prefixes, bucket), and cleans up after itself, so a crashed run cannot break the next one.
- A helper builds the FastAPI app with fakes for unit tests and with real adapters for integration tests.

### 3.4 End-to-end smoke test

`tests/e2e/` gets one test that proves the harness works: start the stack (already up), call `/healthz` and `/readyz` on the `api` container with `httpx`, and check the `X-Trace-Id` header. Real flows are added by `FEAT-1225`. Browser tests for the frontend are decided with the UI libraries in `FEAT-1222`; they are not part of this task.

### 3.5 The docs check

A normal pytest test at unit level (no Docker):

1. Build the app, list every route that is not framework-internal (not `/docs`, `/openapi.json`, `/redoc`).
2. For each route, require the file `docs/apis/<name>.md`. **Name rule:** lower-case method, then the path with `/` turned into `-` and braces dropped. Examples: `POST /v1/jobs` becomes `post-v1-jobs.md`; `GET /v1/jobs/{id}/attempts` becomes `get-v1-jobs-id-attempts.md`; `GET /healthz` becomes `get-healthz.md`.
3. Fail if a doc file exists with no matching route (stale docs), or if a route has no line in `docs/apis/README.md`.
4. Fail if a doc file lacks any of the required headings (method and path, path parameters, query parameters, headers, request body, responses, errors, auth and scopes, rate limits, examples).

This task writes the docs for the three endpoints that exist by then (`/healthz`, `/readyz`, `/metrics`) in the new format, as the template for later ones. `docs/apis/README.md` starts here; `FEAT-1227` completes it.

### 3.6 Coverage

`pytest-cov` is configured to print a report. No minimum percentage yet: a threshold set before there is code is arbitrary. Set one when Phase 1 code exists.

## 4. Tests

The harness is tested by using it: the fakes-based run passes; with the test profile down, an integration test fails with the clear message; with it up, the database fixture migrates and truncates, and a trivial integration test per service passes; the docs check passes on the three endpoints, and fails (shown once in a throwaway test) for a route without a file, a stale file, and a missing heading.

## 5. Check for the same problem elsewhere

Lateral: the "never skip silently" rule is applied to all four service types (Postgres, RabbitMQ, Valkey, storage), not just the first. Causal depth: a test run can pollute the next one in three ways (leftover rows, leftover queues or objects, shared names); each has its own mechanism above (truncate, prefix and cleanup, unique names).

## 6. Side finding for the task list

`ARCHITECTURE.md` section 17 puts "CI" in Phase 0 and D45 chose GitHub Actions, but no item in `TODO.md` builds the workflow. I propose a new item: **Phase 0: GitHub Actions workflow** running ruff, mypy, the unit and contract tests, the docs check, the Compose-based integration tests and the frontend build. It is not part of this task. Logged as `FEAT-20261010-1319` once you agree.

## 7. Out of scope

The CI workflow, frontend test tooling, real end-to-end flows (`FEAT-1225`), the isolation contract test (`FEAT-1226`).

## 8. Questions for you

1. Is the file-name rule in 3.5 acceptable (`post-v1-jobs.md`)?
2. Add the CI workflow as a new item (`FEAT-1319`)?
