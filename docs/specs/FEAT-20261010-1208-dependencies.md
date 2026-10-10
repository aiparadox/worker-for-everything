# FEAT-20261010-1208: install and check the dependencies together

Status: **approved by the user on 2026-10-10** (all questions in the last section answered yes; recommendations accepted as written). Working branch: `feat-20261010-1208-dependencies`, from `master` after `FEAT-1201` is merged. Depends on: `FEAT-20261010-1201`, D45, D46, D47.

## 1. What this builds and why

One approved dependency list, installed into the project environment (`backend/.venv` and `frontend/node_modules` only, never globally) so that we know **before writing real code** that the packages resolve together on Python 3.12 and basically work. Until now the versions were checked only from package metadata (notepad, "Phase 0 verification results"); nothing was installed or run.

This is the single dependency approval for Phase 0 and Phase 1 of the backend (CLAUDE.md Module 5). A package that is not on the list needs a new approval when it is first needed.

## 2. What I checked (2026-10-10, from PyPI and the notepad's verification table)

Every package below declares support for Python 3.12. Versions are the latest at the time; `uv.lock` will pin the exact resolved versions.

## 3. The list for you to approve

### 3.1 Backend, runtime

| Package | Version seen | Used by | Why |
|---|---|---|---|
| fastapi | 0.143.0 | api (`FEAT-1220` and others) | HTTP API (D1) |
| uvicorn | 0.54.0 | api container | runs the API server |
| pydantic, pydantic-settings | 2.14.0, 2.15.0 | config (`FEAT-1203`), API models | validation and the startup config check |
| sqlalchemy (with the `asyncio` extra) | 2.1.4 | data access (D46) | database layer; the `asyncio` extra brings greenlet |
| asyncpg | 0.32.0 | data access | the Postgres driver (must be chosen explicitly, 2.1 defaults to psycopg) |
| alembic | 1.20.0 | migrations (`FEAT-1204`) | schema changes |
| aio-pika | 10.1.0 | queue adapter (`FEAT-1213`) | RabbitMQ client |
| redis | 8.1.0 | rate limiter (`FEAT-1219`) | client library; works with Valkey (D42) |
| pyjwt | 2.15.1 | accounts (`FEAT-1218`) | JWT signing (D33) |
| pwdlib (with the `argon2` extra) | 0.3.1 | accounts | Argon2 password hashing (D33). Still a 0.x release |
| boto3 | 1.43.111 | storage adapter (`FEAT-1214`) | S3 API in a thread pool (D47) |
| httpx | 0.28.1 | tests, FastAPI test client | last released Dec 2024; its Python 3.12 use is tested in this task |
| structlog | 26.1.0 | observability (`FEAT-1205`) | JSON logs with trace id |
| prometheus-client | 0.26.0 | observability | `/metrics` |
| opentelemetry-api, -sdk, -exporter-otlp | 1.45.1 | observability | traces |
| opentelemetry-instrumentation-fastapi, -sqlalchemy, -asyncpg | 0.66b1 | observability | automatic spans. **Beta**; must match the 1.45.x line, so pinned together |

### 3.2 Backend, development only

| Package | Version seen | Why |
|---|---|---|
| ruff | 0.17.0 | lint and format (D45) |
| mypy | 2.4.0 | type check, strict (D45) |
| pytest | 9.1.1 | tests |
| pytest-asyncio | 1.4.0 | async tests |
| pytest-cov | 7.1.0 | coverage |

### 3.3 Frontend

Only what `create-next-app` installs in `FEAT-1201`. UI libraries are chosen in `FEAT-1222` and approved there.

### 3.4 Left out on purpose

`aioboto3`, `aiobotocore` (version conflict, D47), `testcontainers` (D48), `psycopg`, `orjson`, `uuid-utils` (not needed, D41), any pre-commit tool (D45).

## 4. Steps

1. Add the packages with `uv add` (runtime) and `uv add --dev` (development); uv writes `pyproject.toml` and `uv.lock`. Version ranges are "compatible release" ranges (for example `>=0.143,<0.144` style, chosen by uv), with the OpenTelemetry packages pinned exactly.
2. Check that the lock resolves and the environment installs on Python 3.12.
3. Fill the placeholder tests from `FEAT-1201` and run `pytest`, `ruff check`, `ruff format --check`, `mypy`. All must pass.
4. Throwaway checks (kept in a scratch folder, not committed) that need no running service: import every package; a FastAPI app with one route called through the test client (this proves `httpx` on 3.12); encode and decode a JWT with `pyjwt`; hash and verify a password with `pwdlib` and Argon2; build a presigned POST policy with `boto3` (local signing).
5. Frontend: run the generator's `lint` and `build`, and record which TypeScript and ESLint versions the generator chose.
6. Record the exact resolved versions and results in the notepad.

## 5. What this task does not prove (stays open, with an owner)

| Not proven here | Where it is proven |
|---|---|
| SQLAlchemy 2.1 with asyncpg and Alembic against a real Postgres (D46 fallback: 2.0.54) | `FEAT-1204` |
| boto3 against SeaweedFS (presigned POST, HEAD, public URL) | `FEAT-1209` |
| `redis` client against Valkey | `FEAT-1205` readiness check, then `FEAT-1219` |
| aio-pika against RabbitMQ | `FEAT-1213` |
| OpenTelemetry packages exporting to the collector | `FEAT-1205` |

If any of these fails, the fix and the changed decision are logged before moving on.

## 6. Check for the same problem elsewhere

Lateral: the notepad's table lists the same Python-support check for every package, so I re-checked the whole list, not just the risky ones (httpx, pwdlib and the beta OpenTelemetry packages are called out above). Causal depth: a package can declare support and still conflict with another (as `aiobotocore` and `boto3` do), which is why this task installs them all together in one lock.

## 7. Out of scope

Docker images (`FEAT-1202`), config code (`FEAT-1203`).

## 8. Questions for you

1. Approve the list in 3.1 and 3.2? You may strike any package.
2. Approve that the beta OpenTelemetry instrumentation packages are used (pinned exactly)?
