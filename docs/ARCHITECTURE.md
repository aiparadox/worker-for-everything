# Architecture

Status: **Draft for review** · Last updated: 2026-10-08

This document describes how the queue server is built and why. Every choice here comes from the design discussion recorded in [`docs/discussion/NOTEPAD.md`](discussion/NOTEPAD.md). Decision numbers (D1, D2, ...) point to that file.

---

## 1. Purpose

A general-purpose, queue-based job server. Clients submit a job (`type` plus `payload`) over an HTTP API. Workers run the job in the background. Clients check on it and fetch the result.

It must work for any kind of work: document processing, OCR pipelines, content generation, and whatever comes next. It is meant for real-world use at large scale, so reliability, observability and replaceable parts matter more than speed of first delivery.

## 2. Goals and non-goals

**Goals**

- One reliable way to run background work of any type.
- Every piece of infrastructure sits behind an adapter, so it can be replaced (for example RabbitMQ for another broker) by writing one new adapter.
- Every request and every job can be traced across all services with a single trace ID.
- Multi-organisation from day one, with API keys that users create themselves.
- Fully runnable from one `docker compose up`.
- Tested at four levels: unit, integration, adapter contract, end to end.

**Non-goals (for now)**

- Workers written by third parties in other languages (design leaves room, not built).
- Live progress streaming (SSE). Polling is the baseline (D11).
- A full admin console. The frontend only covers signup, login and API keys.

## 3. Decisions at a glance

| Area | Decision | Ref |
|---|---|---|
| Backend | Python with FastAPI, code in `backend/src` | D1 |
| Frontend | Next.js, code in `frontend/src` | D9 |
| Database | PostgreSQL 18 in Docker | D13 |
| Primary keys | UUIDv7 on every table | D13 |
| Broker | RabbitMQ, behind `QueueAdapter` | D5 |
| File storage | MinIO (S3-compatible), behind `StorageAdapter` | D6 |
| Rate limiting | Redis, behind `RateLimiter` | D17 |
| Job work | Handler plugins inside our own workers | D4 |
| Login | Email and password now, OAuth later, behind `AuthProvider` | D7 |
| Tenancy | Organisations with members | D8 |
| API access | API keys created at runtime by logged-in users | D3 |
| Observability | OpenTelemetry, Tempo, Loki, Prometheus, Grafana | D14 |
| Relay | Separate container for publishing the outbox | D12 |

## 4. System overview

```
                         +-----------+
   Browser ------------> | frontend  |  Next.js: signup, login, API keys
                         +-----+-----+
                               | session cookie
                               v
 API client ---------->  +-----------+   writes job + outbox row   +------------+
   (API key)             |    api    | --------------------------> | postgres   |
                         |  FastAPI  | <-- reads status/result --- |            |
                         +--+-----+--+                             +-----+------+
                            |     |  rate limit counters                 ^
                            |     +---------------> +-------+            |
                            |                       | redis |            |
                            | presigned URLs        +-------+            |
                            v                                            |
                         +-------+      reads outbox            +--------+--+
                         | minio | <--------------+             |   relay   |
                         +---^---+                |             +-----+-----+
                             |                    |                   | publishes
                             |            +-------+-----+             v
                             +----------- |   worker    | <------ +----------+
                                 files    |  handlers   |  jobs   | rabbitmq |
                                          +-------------+         +----------+

   All services --> OpenTelemetry collector --> Tempo (traces), Loki (logs), Prometheus (metrics) --> Grafana
```

### Containers (Docker Compose)

| Service | Role | Scales |
|---|---|---|
| `api` | HTTP API. Auth, validation, rate limits, job submit and status | Horizontally |
| `worker` | Consumes jobs from RabbitMQ and runs handlers. Same image as `api`, different command | Horizontally |
| `relay` | Reads the outbox table and publishes to RabbitMQ. Same image, different command | Small number of instances |
| `frontend` | Next.js app | Horizontally |
| `postgres` | System of record for everything | Vertical, read replicas later |
| `rabbitmq` | Delivers "job is ready" messages | Cluster |
| `redis` | Rate limit counters only | Single, later cluster |
| `minio` | Documents, scans, results | Distributed mode |
| `otel-collector`, `tempo`, `loki`, `prometheus`, `grafana` | Observability | See section 12 |

The relay is its own container (D12) so publishing keeps running when the API restarts, and it can be tuned separately.

## 5. Life of a job

1. The client calls `POST /v1/jobs` with an API key.
2. The API checks the key, scopes and rate limits, then validates the payload against the job type's input schema. Bad input is rejected here with a clear error.
3. In **one database transaction** the API inserts the `jobs` row (`queued`) and an `outbox` row. Either both exist or neither does.
4. The relay reads unpublished outbox rows and publishes them to RabbitMQ, then marks them published. This removes the "saved but never queued" gap.
5. A worker receives the message and claims the job by taking a **lease** (a time-limited claim on the job). The job becomes `running`.
6. The worker calls the handler registered for the job type. While it runs, the worker sends heartbeats to extend the lease and may report progress.
7. On success the result is saved and the job becomes `succeeded`. Only **then** is the RabbitMQ message acknowledged.
8. On failure the job is retried with backoff, and after the last attempt it goes to the dead-letter queue and becomes `failed`.
9. The client polls `GET /v1/jobs/{id}` for status, progress and result.

### State machine

```
queued --> running --> succeeded
              |
              +--> retrying --> queued ...   (until max_attempts)
              |
              +--> failed                    (permanent error, or attempts used up)

Phase 2 adds: queued/retrying --> cancelled
```

## 6. Code structure and the adapter rule

```
backend/
  src/
    domain/          Pure business rules. Job, Organisation, ApiKey, state transitions.
    ports/           Interfaces only (see table below).
    adapters/        One folder per technology: postgres/, rabbitmq/, minio/, redis/, password_auth/
    application/     Use cases (SubmitJob, CreateApiKey, ...). Depend on ports only.
    handlers/        Job-type plugins. `echo` for tests, then real ones (OCR etc.).
    api/             FastAPI routes, request and response models, auth and rate limit middleware.
    worker/          Consumer loop, lease and heartbeat, retry logic.
    relay/           Outbox publisher loop.
    observability/   Logging, tracing, metrics setup.
    config/          Settings, validated at startup.
  tests/
    unit/  integration/  contract/  e2e/
  migrations/        Alembic
frontend/src/        Next.js app
docs/                ARCHITECTURE.md, apis/, adr/, specs/, discussion/
```

**The rule that makes parts replaceable:** `domain/` and `application/` never import from `adapters/`. They only know the interfaces in `ports/`. A single wiring module chooses which adapter to use for each port, based on configuration.

| Port | First implementation | Could be replaced by |
|---|---|---|
| `QueueAdapter` | RabbitMQ | Postgres queue, Redis Streams, SQS |
| `StorageAdapter` | MinIO (S3 API) | AWS S3, GCS, local disk |
| `RateLimiter` | Redis | In-memory (tests), other stores |
| `AuthProvider` | Email and password | Google, GitHub, other OAuth |
| `JobRepository` and other repositories | PostgreSQL | Other databases |
| `Clock`, `IdGenerator` | System clock, UUIDv7 | Fakes in tests |

## 7. Data model

All primary keys are **UUIDv7** (D13). They are time-ordered, so inserts land at the end of the index instead of scattering across it as random UUIDv4 would. Postgres 18 generates them with `DEFAULT uuidv7()`. The application may also generate one when it needs the id before inserting.

| Table | Purpose |
|---|---|
| `organisations` | A tenant. Owns keys, jobs and usage. |
| `users` | A person who can log in. |
| `memberships` | User, organisation, role. |
| `api_keys` | Organisation, name, prefix, secret hash, scopes, created_by, last_used_at, expires_at, revoked_at. |
| `jobs` | id, organisation, type, payload (JSON), status, attempts, max_attempts, progress, result or a file reference, error, idempotency_key, trace_id, timestamps. Phase 2 fields exist from the start: `priority`, `run_at`, `cancel_requested`. |
| `job_attempts` | One row per try: start, end, outcome, error. Shows why a job failed. |
| `outbox` | Rows waiting to be published to RabbitMQ. |

- `(organisation_id, idempotency_key)` is unique. If a client retries a submit after a network error, it gets the same job back, not a duplicate.
- The jobs table is expected to grow large. UUIDv7 ordering makes time-based partitioning and archiving possible later. It is not built in Phase 1.
- Schema changes go through Alembic migrations only.

## 8. Authentication and authorisation

Two kinds of credentials, kept apart on purpose:

| | Browser session | API key |
|---|---|---|
| Used by | The Next.js frontend | Programs calling the API |
| Carried as | httpOnly cookie | `Authorization: Bearer <key>` |
| Can do | Sign up, log in, manage API keys | Use the job APIs, within its scopes |
| Cannot do | Call the job APIs | Create or revoke API keys |

**API keys**

- Format: `qfe_<prefix>_<random secret>`.
- The full key is shown **once**, at creation. Only a hash is stored.
- Lookup is by prefix, comparison is constant-time.
- Each key has scopes (for example `jobs:read`, `jobs:write`), an optional expiry, and can be revoked immediately.
- The secret is random and unrelated to any UUID.

**Passwords** are hashed with Argon2. Login goes through the `AuthProvider` port, so OAuth providers can be added later without touching the rest of the system (D7).

**Authorisation:** every query is scoped by the organisation of the credential. A key can never see another organisation's jobs.

## 9. Rate limiting

Required in Phase 1 (D16, D17). Counters live in Redis behind the `RateLimiter` port.

| Limit | Applies to | Protects against |
|---|---|---|
| Requests per API key | Each key | One key hammering the API |
| Requests per organisation | All keys of an organisation together | Creating many keys to get around the key limit |
| Active jobs per organisation | Jobs in `queued`, `retrying` or `running` | One organisation filling the queue and starving others |
| Login and signup per IP address | Unauthenticated auth endpoints | Password guessing and fake signups |

**When a limit is hit:** the API answers `429 Too Many Requests` with a `Retry-After` header and a JSON error body. Normal responses carry rate limit headers so clients can slow down on their own.

**When Redis is down** (D18, explicit by design):

- Job and general API limits **fail open**: requests are allowed, and the system logs an error, increments a metric and raises an alert.
- Login and signup limits **fail closed**: requests are rejected, because without limits they are open to abuse.

The code that applies this lives in one place, is named for what it does, and logs every time it triggers. This is a "for now" choice the team may revisit.

Limit values are configuration with safe defaults (tuning knobs, not required secrets). Per-organisation overrides are a later extension.

**Documentation:** a dedicated `docs/rate-limits.md` explains every limit, the headers, the 429 body and the Redis-outage behaviour. Every endpoint doc in `docs/apis/` states which limits apply to it.

## 10. Job handlers (how new work plugs in)

Each job type is a class in `backend/src/handlers/` that defines:

- a name and version, for example `ocr.extract`
- an **input schema** and an **output schema** (Pydantic)
- settings: timeout, max attempts, retry delays
- one method, `handle(context, payload)`

The `context` gives the handler: job id, trace ID, organisation, attempt number, the storage adapter, `report_progress(percent)`, and a logger already tagged with the trace ID.

Handlers are **registered explicitly** in one file, not discovered by magic, so what a worker can run is visible in the code. `GET /v1/job-types` lists the registered types and their input schemas.

**Hard rule:** delivery is at-least-once (section 11), so every handler must be safe to run twice for the same job.

**Errors**

- `PermanentError`: bad input, unsupported file, and similar. Fails at once, no retries.
- Anything else, including unexpected exceptions and timeouts, is retried until `max_attempts`. This default is deliberate, documented, and logged.

## 11. Reliability and delivery

- **Transactional outbox** for submit (section 5): a job can never be saved without being queued, or queued without being saved.
- **At-least-once delivery.** A message is acknowledged only after the worker has committed the outcome to Postgres.
- **Leases and heartbeats.** If a worker dies, its lease expires and a recovery process requeues the job.
- **Retries** use exponential backoff with jitter. In RabbitMQ this is done with delay queues that dead-letter back into the main queue. Phase 2 delayed jobs reuse the same mechanism.
- **Dead-letter queue.** After the last attempt the job moves there and is marked `failed`. All attempts stay in `job_attempts`.
- **Idempotent submit** through the idempotency key (section 7).
- **Backpressure.** Worker prefetch is limited so a worker never grabs more than it can run.

## 12. Observability

**Trace ID everywhere**

- Every request gets a trace ID using the W3C `traceparent` format. If the client sends none, one is generated.
- It is returned in the `X-Trace-Id` response header, saved on the job, and sent as a RabbitMQ message header.
- The worker and relay continue the same trace. API, relay and worker log lines for one job share one trace ID.

**Logs:** structured JSON. Every line carries `trace_id`, `span_id`, and, where known, `org_id` and `job_id`.

**Metrics** (`/metrics`): request rate and latency, queue depth, job duration by type, retries, dead-letter count, rate limit rejections, Redis fallback events.

**Stack:** OpenTelemetry collector, Tempo (traces), Loki (logs), Prometheus (metrics), Grafana (dashboards and alerts). Alerts cover dead-letter growth, growing queue depth, Redis fallback, and elevated error rates.

**Health:** `/healthz` (process is up) and `/readyz` (dependencies reachable).

## 13. Testing

| Level | What it covers | Runs against |
|---|---|---|
| Unit | Domain and use cases | In-memory fake adapters. Fast, no Docker. |
| Integration | Each adapter against the real service | Real Postgres, RabbitMQ, Redis, MinIO |
| Contract | One shared test suite that every implementation of a port must pass | Every adapter of that port |
| End to end | Full flows through the complete Compose stack | Everything |
| Docs check | Every route has a matching file in `docs/apis/` | Source and docs |

Contract tests are what make "replace RabbitMQ with something else" safe: the new adapter must pass the same suite.

**End-to-end flows (at least):** signup, login, create key, submit job, worker runs, fetch result · failing job, retries, dead-letter · rate limit hit and recovery · revoked key rejected · idempotent resubmit.

How integration tests start their services (throwaway containers from test code, or a shared Compose test profile) is still open and will be settled when versions are pinned.

## 14. API documentation rules

- Every endpoint has its own file: `docs/apis/<endpoint>.md`, covering method, path, path parameters, query parameters, headers, request body, responses, errors, auth needed, scopes, and applicable rate limits, with examples.
- `docs/apis/README.md` is a short list of all endpoints with one line each.
- The docs check (section 13) fails the build when an endpoint has no doc file.
- FastAPI's generated OpenAPI is a secondary reference. The markdown files are the maintained documentation.

## 15. Configuration

- Everything required to run (secrets, connection URLs, credentials) is **validated at startup**. A missing or invalid value stops the service immediately, with a clear message. There are no hidden defaults that boot with wrong config.
- Pure tuning values with a safe default (timeouts, limits, retry delays) may have defaults in code.
- Any fallback must be visible: named, logged, and obvious in the code.

## 16. Security notes

- API key secrets and passwords are never stored in plain text and never logged.
- Payloads and results may contain sensitive documents. Logs record ids and sizes, not content.
- Files are exchanged through storage references and short-lived presigned URLs, not through the queue.
- All inputs are validated against schemas. All queries are scoped by organisation.
- Cookies are httpOnly, secure and same-site. CORS is an explicit allowlist.

## 17. Roadmap

| Phase | Scope |
|---|---|
| **0, Foundation** | Repo layout, Compose stack, startup config validation, observability skeleton, CI, docs check |
| **1, Core** | Organisations, signup and login, API keys and their Next.js pages, submit job, status, result, worker, retries and dead-letter, rate limiting (all four limits), `echo` handler plus one real sample handler, e2e flows, API docs, rate limit docs |
| **2** | Priorities, delayed jobs, cancel, completion webhooks |
| **Wishlist** | OAuth providers, other queue adapters, per-organisation limit overrides, time partitioning of `jobs`, external workers, SSE |

## 18. Open items

These must be settled before or during Phase 0. None of them changes the shape of the design.

1. **Version pinning.** Check on PyPI and official docs that FastAPI, SQLAlchemy, asyncpg, Alembic, the RabbitMQ client, OpenTelemetry packages and Next.js support the chosen Python version. Confirm the `postgres:18` image tag exists.
2. **Python version.** UUIDv7 in the standard library needs Python 3.14. If libraries do not support it yet, either let Postgres generate every id, or pin an older Python and use a small library for app-side ids.
3. **Integration test setup** (throwaway containers vs Compose test profile).
4. **Default limit values** for the four rate limits.
5. **Which real sample handler** ships in Phase 1.

## 19. Known risks

- **At-least-once delivery** means duplicate runs are possible. Mitigation: idempotent handlers as a hard rule, and tests that run each handler twice.
- **Redis outage** opens API limits (by decision). Mitigation: alert and metric on every fallback.
- **One large `jobs` table.** Mitigation: UUIDv7 ordering, the right indexes, and a documented partitioning path.
- **Operational weight.** The stack has many containers. Mitigation: everything is in one Compose file, and the observability stack can be switched off for light local work.
