# Architecture

Status: **Draft for review** · Last updated: 2026-10-10

This document describes how the queue server is built and why. Every choice here comes from the design discussion recorded in [`docs/discussion/NOTEPAD.md`](discussion/NOTEPAD.md). Decision numbers (D1, D2, ...) point to that file. Table and column detail is in [`DATABASE.md`](DATABASE.md).

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
- Tested at four levels (unit, integration, adapter contract, end to end), plus a docs check.

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
| Broker | RabbitMQ, behind `QueueAdapter`. **One queue per job type** | D5, D28 |
| File storage | SeaweedFS (S3-compatible) in Docker, behind `StorageAdapter`. MinIO was dropped because its community edition is archived | D6, D20 |
| File upload | Presigned upload through `POST /v1/files`, jobs carry file ids | D31 |
| Rate limiting | Redis for the three request-rate limits, behind `RateLimiter`. The active-jobs cap is counted in Postgres | D17, D29 |
| Job work | Handler plugins inside our own workers | D4 |
| Login | Email and password now, OAuth later, behind `AuthProvider`. Access and refresh JWTs | D7, D32 |
| Tenancy | Organisations with members. Signup creates the user's first organisation | D8, D30 |
| API access | API keys created at runtime by logged-in users | D3 |
| Observability | OpenTelemetry, Tempo, Loki, Prometheus, Grafana | D14 |
| Relay | Separate container for publishing the outbox | D12 |
| Background chores | Separate `maintenance` container (lease recovery, safety-net sweep, cleanup, purge) | D19, D27 |
| Retries and delays | New outbox rows with a `run_at` time. No broker delay queues, no dead-letter queue | D22, D24, D25 |
| Acknowledgement | A worker acks the RabbitMQ message right after its claim is saved | D23 |
| Worker pools | Each worker container serves the job types in `WORKER_JOB_TYPES` (a required setting, `*` means all types), with its own concurrency | D35, D39 |
| Phase 1 accounts | Signup and login only. Email verification, password reset and invitations are deferred | D30 |

## 4. System overview

```
                         +-----------+
   Browser ------------> | frontend  |  Next.js: signup, login, API keys
                         +-----+-----+
                               | access token (memory) + refresh cookie
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
                         | store | <--------------+             |   relay   |
                         +---^---+                |             +-----+-----+
                             |                    |                   | publishes
                             |            +-------+-----+             v
                             +----------- |   worker    | <------ +----------+
                                 files    |  pools      |  jobs   | rabbitmq |
                                          +-------------+         +----------+
                                                                  (one queue per job type)

   All services --> OpenTelemetry collector --> Tempo (traces), Loki (logs), Prometheus (metrics) --> Grafana
```

### Containers (Docker Compose)

| Service | Role | Scales |
|---|---|---|
| `api` | HTTP API. Auth, validation, rate limits, job submit and status, file upload links | Horizontally |
| `worker` (one or more pools) | Consumes the queues of its job types and runs handlers. Same image as `api`, different command. Each pool sets `WORKER_JOB_TYPES` and its own concurrency | Horizontally, per pool |
| `relay` | Reads outbox rows that are due and publishes them to RabbitMQ. Same image, different command | Small number of instances |
| `maintenance` | Background chores: lease recovery, the safety-net sweep, cleanup of outbox rows, expired refresh tokens and unused files, job purge. Same image, different command. Not drawn in the diagram | Several copies are safe, each chore claims work with `SKIP LOCKED` |
| `frontend` | Next.js app | Horizontally |
| `postgres` | System of record for everything | Vertical, read replicas later |
| `rabbitmq` | Delivers "job is ready" messages, one queue per job type | Cluster |
| `redis` | Rate limit counters only | Single, later cluster |
| `storage` (SeaweedFS) | Documents, scans, results. Shown as `store` in the diagram | Distributed mode |
| `otel-collector`, `tempo`, `loki`, `prometheus`, `grafana` | Observability | See section 12 |

The relay is its own container (D12) so publishing keeps running when the API restarts, and it can be tuned separately. The `maintenance` container is separate from the relay (D19) so a slow cleanup can never delay publishing.

### Worker pools and concurrency (D35)

A worker is one process. Its **concurrency** is how many jobs it runs at the same time, and it is set per pool:

- `ocr.extract` runs with concurrency 1 (one heavy job per process). To process more at once, run more containers.
- Email sending might run at a higher concurrency, tuned after load testing.

`WORKER_JOB_TYPES` lists the job types a pool serves. The worker consumes only those queues. The setting is **required**: if it is missing, the worker does not start. The value `*` means "every type this worker has code for". That is fine in development, and a conscious choice anywhere else, so a production OCR pool can never quietly start serving email jobs too (D39). Startup also fails if a listed type does not exist.

Separate queues alone do not stop a flood of slow jobs from using up every worker. Separate **pools** do, so slow and fast job types should run in different pools.

## 5. Life of a job

1. The client calls `POST /v1/jobs` with an API key.
2. The API checks the key, scopes and request rate limits, then validates the payload against the job type's input schema. Bad input is rejected here with a clear error. Then, **before any transaction or lock**, the API checks each file the payload refers to: it belongs to the organisation, and a HEAD request to storage finds the object. A found file is marked `available`.
3. In **one database transaction** the API takes a per-organisation lock, checks the idempotency key, re-reads the file rows from the database (still `available`, same organisation, not expired) and locks them so cleanup skips them, checks the active-jobs cap, then inserts the `jobs` row (`queued`), the `job_files` rows and an `outbox` row. No network call is made while the lock is held (D36), so the lock lasts a few milliseconds. Either everything exists or nothing does.
4. The relay reads outbox rows that are due (their `run_at` has passed) and publishes each one to the RabbitMQ queue named after the job type. It marks a row published only after RabbitMQ confirms the message was received **and** routed to a queue.
5. A worker in a pool that serves that type receives the message. It tries to **claim** the job: one transaction that only succeeds if the job is still waiting and its `run_at` has passed. The claim takes a **lease** (a time-limited ownership) and a **lease token** (a random code), sets the job to `running`, and records a `job_attempts` row.
6. **Claim succeeded:** the transaction commits, the worker **acks** the message, and runs the handler. While it runs, it sends heartbeats that extend the lease.
7. **Claim refused** (the job is finished, owned by someone else, or not due yet): the worker acks the message and logs the reason. This is not an error. If a message is needed later, a later message arrives.
8. **Handler succeeds:** in one transaction, guarded by the lease token, the job becomes `succeeded`, the result is saved, and the attempt row is closed.
9. **Handler fails with attempts left:** in one transaction, guarded by the lease token, the job becomes `retrying`, `jobs.run_at` is set to `now()` plus the backoff delay, the attempt is closed, and a new outbox row with the same `run_at` is inserted. The worker never publishes to RabbitMQ to requeue (D22).
10. **Permanent error, or attempts used up:** in one transaction, guarded by the lease token, the job becomes `failed`, the error is stored, and the attempt is closed. There is no dead-letter queue (D25). `jobs.status = 'failed'` plus `job_attempts` is the record.
11. The client polls `GET /v1/jobs/{id}` for status, progress and result.

**Crash rules**

- Crash **before** the claim commits: the message was never acked, so RabbitMQ delivers it again. Nothing in the database changed, so this is correct.
- Crash **after** the claim: the lease runs out and recovery (in `maintenance`) takes over (section 11).

### State machine

```
queued ---claim---> running ---success------------------------------> succeeded
                      |
                      +--handler error, attempts left---------------> retrying --claim (after run_at)--> running
                      +--permanent error / attempts used up---------> failed
                      +--lease expired (recovery), attempts left----> retrying
                      +--lease expired (recovery), attempts used up-> failed

Phase 2 adds: queued / retrying --> cancelled
```

`queued` is used only before the first run. A retry goes to `retrying` and is claimed from there. It never goes back to `queued`. `max_attempts` counts the first run plus the retries.

## 6. Code structure and the adapter rule

```
backend/
  src/
    domain/          Pure business rules. Job, Organisation, ApiKey, state transitions, retry delay calculation.
    ports/           Interfaces only (see table below).
    adapters/        One folder per technology: postgres/, rabbitmq/, s3/ (object storage), redis/, password_auth/
    application/     Use cases (SubmitJob, CreateApiKey, CreateUploadLink, ...). Depend on ports only.
    job_types/       Light definitions: name, version, input and output schemas, retry settings. No heavy imports.
    handlers/        Handler implementations. May import heavy libraries (OCR and so on). Only workers load them.
    api/             FastAPI routes, request and response models, auth and rate limit middleware.
    worker/          Consumer loop, concurrency control, lease and heartbeat, retry logic.
    relay/           Outbox publisher loop.
    maintenance/     Lease recovery, sweep, cleanups, purge.
    observability/   Logging, tracing, metrics setup.
    config/          Settings, validated at startup.
  tests/
    unit/  integration/  contract/  e2e/
  migrations/        Alembic
frontend/src/        Next.js app
docs/                ARCHITECTURE.md, DATABASE.md, apis/, adr/, specs/, discussion/
```

**The rule that makes parts replaceable:** `domain/` and `application/` never import from `adapters/`. They only know the interfaces in `ports/`. A single wiring module chooses which adapter to use for each port, based on configuration.

**Why `job_types/` and `handlers/` are separate:** the API and the relay need to know which job types exist and what their input looks like, but they must not load OCR or AI libraries. The light definitions are shared. The heavy implementations are loaded only by workers.

| Port | First implementation | Could be replaced by |
|---|---|---|
| `QueueAdapter` | RabbitMQ, one queue per job type | Postgres queue, Redis Streams, SQS |
| `StorageAdapter` | SeaweedFS (S3 API) | AWS S3, GCS, local disk |
| `RateLimiter` | Redis | In-memory (tests), other stores |
| `AuthProvider` | Email and password | Google, GitHub, other OAuth |
| `JobRepository` and other repositories | PostgreSQL | Other databases |
| `Clock`, `IdGenerator` | System clock, UUIDv7 | Fakes in tests |

## 7. Data model

All primary keys are **UUIDv7** (D13). They are time-ordered, so inserts land at the end of the index instead of scattering across it as random UUIDv4 would. Postgres 18 generates them with `DEFAULT uuidv7()`. The application may also generate one when it needs the id before inserting.

| Table | Purpose |
|---|---|
| `organisations` | A tenant. Owns keys, jobs, files and usage. |
| `users` | A person who can log in. |
| `auth_identities` | How a user proves who they are: a password now, OAuth providers later (D7). |
| `refresh_tokens` | One row per refresh token, with a family id and an absolute family expiry, so rotation, reuse detection and a maximum login lifetime work (D32, D37, D40). |
| `memberships` | User, organisation, role. |
| `api_keys` | Organisation, name, prefix, secret hash, scopes, created_by, last_used_at, expires_at, revoked_at. |
| `files` | Uploaded inputs and stored results, referenced by id (D31). |
| `job_files` | Links a job to its **input** files, so cleanup never removes a file a job still needs. A result file is linked by `jobs.result_file_id`, so each file has one link (D40). |
| `jobs` | id, organisation, type, payload (JSON), status, attempts, max_attempts, progress, result or a result file, error, idempotency_key, trace_id, `run_at` (do not run before), lease fields, sweep fields (`sweep_count`, `last_enqueued_at`), timestamps. Phase 2 fields `priority` and `cancel_requested` exist from the start. |
| `job_attempts` | One row per try: start, end, outcome, error. Shows why a job failed. |
| `outbox` | Messages waiting to be published to RabbitMQ, each with a `reason` and a `run_at` time. A job gets a new row for its first run and for every retry, recovery or sweep (D22, D27). |

- `(organisation_id, idempotency_key)` is unique. If a client retries a submit after a network error, it gets the same job back, not a duplicate.
- The jobs table is expected to grow large. UUIDv7 ordering makes time-based partitioning and archiving possible later. It is not built in Phase 1.
- `jobs` also holds the lease fields (`lease_owner`, `lease_token`, `lease_expires_at`). Heartbeats and the final write must match the lease token; zero rows updated means the lease was lost.
- Schema changes go through Alembic migrations only.

## 8. Authentication and authorisation

Two kinds of credentials, kept apart on purpose:

| | Browser login | API key |
|---|---|---|
| Used by | The Next.js frontend | Programs calling the API |
| Carried as | Access token in the `Authorization: Bearer` header (kept in browser memory), plus a refresh cookie | `Authorization: Bearer <key>` |
| Can do | Sign up, log in, manage API keys | Use the job and file APIs, within its scopes |
| Cannot do | Call the job APIs | Create or revoke API keys |

**Browser login (D32)**

- **Access token:** a signed JWT lasting about 15 minutes, held in browser memory. Claims: `iss`, `aud`, `sub`, `exp`, `iat`, `jti`, `org_id`, `role`, `fam`.
- **Refresh token:** also a signed JWT, in an httpOnly, Secure, `SameSite=Strict` cookie that is sent only to the refresh path. It has its own audience and `typ: refresh`, so the two token types can never be used in place of each other.
- **Server side:** each refresh token has a row in `refresh_tokens`. Every refresh **rotates** the token: the old one is marked used and a new one is issued.
- **Reuse window (D37).** Two browser tabs, or a reload during a refresh, can send the same refresh token twice within moments. So a used token shown again **within a short window** (a tuning value, for example 10 to 30 seconds) gets a distinct "already refreshed" error and nothing is revoked. The browser's cookie already holds the new token from the first response, so the frontend retries once and succeeds. The frontend also lets only one tab refresh at a time. A used token shown again **after** the window is treated as theft and the whole token family is revoked.
- **Absolute lifetime (D40).** Each login sets a `family_expires_at` that is never extended by rotation. After it, refresh is refused and the user logs in again.
- **Logout** revokes the family. The access token stays valid until it expires (at most about 15 minutes). This is accepted.
- **API key management** re-reads the user and membership from the database on every call, so a changed role takes effect at once for that sensitive area.
- The signing secret, issuer and audience are required configuration and fail at startup if missing.
- **Deployment rule (D40):** `SameSite=Strict` means the frontend and the API must be on the same site (for example `app.example.com` and `api.example.com`; different ports on `localhost` are fine). Frontend and API on different registrable domains would break login. The alternative is to have the Next.js server proxy API calls on its own origin.

**API keys**

- Format: `qfe_<prefix>_<random secret>`.
- The full key is shown **once**, at creation. Only a hash is stored.
- Lookup is by prefix, comparison is constant-time.
- Each key has scopes (`jobs:read`, `jobs:write`, `files:read`, `files:write`), an optional expiry, and can be revoked immediately.
- The secret is random and unrelated to any UUID.

**Passwords** are hashed with Argon2. Login goes through the `AuthProvider` port, so OAuth providers can be added later without touching the rest of the system (D7). The libraries (PyJWT and pwdlib) are not added yet; versions are checked in Phase 0 first (D33).

**Signup (D30):** accepts any email address in Phase 1, because email verification is deferred. It creates the user's first organisation automatically, with the user as `owner`.

**Authorisation:** every query is scoped by the organisation of the credential. A key can never see another organisation's jobs or files. A contract test proves this for every repository method (see section 13).

**OAuth rule for later (D7):** an OAuth login is never linked to an existing user just because the email matches, unless the provider states that the email is verified. Linking on an unverified email is a known account-takeover route.

## 9. Rate limiting

Required in Phase 1 (D16, D17). Three request-rate limits live in Redis behind the `RateLimiter` port. The fourth limit is a live count, so it lives in Postgres (D29).

| Limit | Applies to | Protects against | Where |
|---|---|---|---|
| Requests per API key | Each key | One key hammering the API | Redis |
| Requests per organisation | All keys of an organisation together | Creating many keys to get around the key limit | Redis |
| Login and signup per IP address | Unauthenticated auth endpoints | Password guessing and fake signups | Redis |
| Active jobs per organisation | Jobs in `queued`, `retrying` or `running` | One organisation filling the queue and starving others | Postgres, counted up to the cap inside the submit transaction |
| Refresh and logout | Per IP and per user, **separate from login** | Token-refresh abuse | Redis, fails open (D40) |

**Per-IP limits and proxies (known gap).** Phase 1 ignores forwarded headers and uses the connection's address. Behind any proxy or load balancer, all users then share one address, so the per-IP login limit does not work as intended. This is deferred (see the Deferred list in the notepad) and must be stated in `docs/rate-limits.md`. It is only valid for local development or a direct connection.

**When a limit is hit:** the API answers `429 Too Many Requests` with a `Retry-After` header and a JSON error body. Normal responses carry rate limit headers so clients can slow down on their own.

**When Redis is down** (D18, explicit by design, revised by D29):

- API, organisation, refresh and logout request limits **fail open**: requests are allowed, and the system logs an error, increments a metric and raises an alert. Refresh has its own limit, separate from login, so that a Redis outage can never block refreshes and log everyone out.
- Login and signup limits **fail closed**: requests are rejected, because without limits they are open to abuse.
- The **active-jobs cap does not depend on Redis**, so it keeps working during a Redis outage.

The code that applies this lives in one place, is named for what it does, and logs every time it triggers. This is a "for now" choice the team may revisit.

**The active-jobs cap** is counted inside the submit transaction after taking a per-organisation advisory lock, so concurrent submits can never exceed the cap. The count stops at the cap, so it stays cheap. The cap should stay in the low thousands. Details are in `DATABASE.md` section 6.

Limit values are configuration with safe defaults (tuning knobs, not required secrets). Per-organisation overrides are a later extension.

**Documentation:** a dedicated `docs/rate-limits.md` explains every limit, the headers, the 429 body, the Redis-outage behaviour and the proxy caveat. Every endpoint doc in `docs/apis/` states which limits apply to it.

## 10. Job types and handlers (how new work plugs in)

Each job type has two parts:

- a **definition** in `job_types/`: name and version (for example `ocr.extract`), an **input schema** and an **output schema** (Pydantic), and settings (timeout, max attempts, retry delays)
- a **handler** in `handlers/`: one method, `handle(context, payload)`

The `context` gives the handler: job id, trace ID, organisation, attempt number, the storage adapter, `report_progress(percent)`, and a logger already tagged with the trace ID.

Definitions are **registered explicitly** in one file, not discovered by magic, so what the system can run is visible in the code. `GET /v1/job-types` lists the registered types and their input schemas.

**Files in payloads.** An input schema declares file fields with a typed `FileRef` (for example `document: FileRef`). That is how the API finds file ids inside a free-form payload and checks, at submit, that each file belongs to the organisation and exists.

**Hard rule:** delivery is at-least-once (section 11), so every handler must be safe to run twice for the same job.

**Errors**

- `PermanentError`: bad input, unsupported file, and similar. Fails at once, no retries.
- Anything else, including unexpected exceptions and timeouts, is retried until `max_attempts`. This default is deliberate, documented, and logged.

**Retry delay.** One function in `domain/` returns a **duration** with random jitter for a given attempt number and the job type's retry settings. It does not return a timestamp. SQL then writes `run_at = now() + :delay` on the database clock (D24). The default plan (to be confirmed per job type) is 3 retries after the first run (`max_attempts` = 4), with delays of about 10 seconds, 2 minutes and 10 minutes, jitter about ±20%. Lease recovery uses the same function, so a job that crashes its worker (for example by running out of memory) is not retried at once.

## 11. Reliability and delivery

- **Transactional outbox** for submit and for every requeue (section 5, D22): a job can never be saved without being queued, or queued without being saved.
- **One queue per job type (D28).** Direct exchange; `outbox.routing_key` is the job type. Every process that knows a type (api, relay, worker) idempotently declares that type's durable queue and binding at startup. Messages for a type wait in its queue until a worker for that type starts, so rolling deploys are safe.
- **Publishing.** The relay publishes with the mandatory flag and publisher confirms. An unroutable message is returned by RabbitMQ before it is confirmed; the relay treats that as a **failed publish**: `published_at` stays null and `publish_attempts` and `last_error` are updated. Without the mandatory flag RabbitMQ would confirm and silently drop such a message. A row that fails repeatedly is logged, counted and alerted on (it is not failed automatically in Phase 1).
- **Ack after claim (D23).** The worker acks the message as soon as its claim commits, or is refused. It does not wait for the job to finish. This avoids RabbitMQ's acknowledgement timeout for long jobs (30 minutes by default).
- **Concurrency.** Prefetch no longer limits how many jobs run, because acked messages free their place. A worker consumes only while it has free concurrency and cancels its consumers when it is full. Messages already on their way can still arrive, so a worker may briefly hold **at most one delivered, unclaimed message per queue**. If it cannot start one within a short wait (a tuning value), it nacks it with requeue so another worker can take it. The RabbitMQ consumer timeout stays an explicit setting.
- **Lease token.** Every heartbeat and final write says `WHERE id = ? AND status = 'running' AND lease_token = ?`. Zero rows updated means the worker lost its lease and must stop. The attempt is recorded as `lease_lost`.
- **At-least-once.** Nothing is lost, and a job may rarely run twice. The claim refuses a job that is already running, finished, or not yet due, so duplicate messages are harmless. Handlers stay idempotent.
- **Recovery** (in `maintenance`): finds `running` jobs whose lease expired. If `attempts >= max_attempts` the job is marked `failed`. Otherwise it becomes `retrying`, its `run_at` is set to `now()` plus the same backoff delay used for retries, and a new outbox row is inserted. Either way the open attempt is closed as `lease_lost`. A job that crashes every worker therefore fails after `max_attempts`.
- **Safety-net sweep** (in `maintenance`, D27). After an early ack, a message that was acked without a claim leaves a job with no owner and no message, and recovery only looks at `running` jobs. The sweep finds jobs that are `queued` or `retrying`, whose `run_at` is older than a wait, whose `last_enqueued_at` is older than the wait, and that have no unpublished outbox row. It inserts a new outbox row (`reason = 'sweep'`). The wait grows each time the same job is swept: 5, 10, 20, 40 minutes, capped at 1 hour, so a deep backlog is never flooded with duplicates. The history lives in two fields **on the job** (`sweep_count` and `last_enqueued_at`, updated in the same transaction as every outbox insert, and `sweep_count` reset when a worker claims the job), not in the outbox table, so deleting old outbox rows can never reset the wait (D38). The sweep cannot tell a lost message from a slow queue, which is why it waits longer each time. A duplicate message it sends is harmless: the claim refuses a job that is already running, finished, or not yet due. Each run handles a bounded number of jobs, one transaction per job, claimed with `SKIP LOCKED`. Every sweep re-queue logs a warning, increments a metric and can alert, because it should be rare and usually means a bug.
- **Unprocessable message** (unknown job id, corrupt body): ack, log an error with the message size only, count a metric. The sweep covers the job if one exists.
- **Unknown job type** (misconfiguration only, since workers consume only their own queues): do not claim, ack, log an error, count a metric. The sweep re-queues it.
- **Retries** use exponential backoff with jitter, with the delay held as `run_at` (section 10). There are no RabbitMQ delay queues, so the broker stays swappable. Delay precision equals the relay's polling interval (about a second). Phase 2 delayed jobs reuse the same mechanism.
- **No dead-letter queue (D25).** Failures are read from the database.
- **Idempotent submit.** The idempotency key is checked under the organisation lock. If two requests with the same key still collide, the unique-violation error is caught and the existing job is returned.
- **Fairness between organisations.** A job type's queue is first-in-first-out across all organisations. The active-jobs cap limits how much one organisation can queue. Fair scheduling between organisations is on the wishlist.

## 12. Observability

**Trace ID everywhere**

- Every request gets a trace ID using the W3C `traceparent` format. If the client sends none, one is generated.
- It is returned in the `X-Trace-Id` response header, saved on the job, and sent as a RabbitMQ message header.
- The worker and relay continue the same trace. API, relay and worker log lines for one job share one trace ID.

**Logs:** structured JSON. Every line carries `trace_id`, `span_id`, and, where known, `org_id` and `job_id`.

**Metrics** (`/metrics`): request rate and latency, queue depth per job type, job duration by type, retries, `jobs_failed_total` by job type and error code, sweep re-queues, stuck outbox rows, rate limit rejections, Redis fallback events. `job_type` is a safe metric label; `org_id` and `job_id` are not (too many values).

**Stack:** OpenTelemetry collector, Tempo (traces), Loki (logs), Prometheus (metrics, including RabbitMQ's own Prometheus metrics), Grafana (dashboards and alerts).

**Alerts:** a queue has messages but no consumers; queue depth growing per job type; elevated failed-job rate; sweep re-queues; a stuck outbox row; Redis fallback; elevated error rates.

**Inspecting failures:** read them through the API (`GET /v1/jobs?status=failed` and `GET /v1/jobs/{id}/attempts`) and the metric above.

**Health:** `/healthz` (process is up) and `/readyz` (dependencies reachable).

## 13. Testing

| Level | What it covers | Runs against |
|---|---|---|
| Unit | Domain and use cases | In-memory fake adapters. Fast, no Docker. |
| Integration | Each adapter against the real service | Real Postgres, RabbitMQ, Redis, SeaweedFS |
| Contract | One shared test suite that every implementation of a port must pass | Every adapter of that port |
| End to end | Full flows through the complete Compose stack | Everything |
| Docs check | Every route has a matching file in `docs/apis/` | Source and docs |

Contract tests are what make "replace RabbitMQ with something else" safe: the new adapter must pass the same suite. The `QueueAdapter` suite must cover "one queue per type" and "an unroutable publish is reported".

**End-to-end flows (at least):** signup, login, create key, upload a file, submit job, worker runs, fetch result · failing job, retries, then `failed` · rate limit hit and recovery · revoked key rejected · idempotent resubmit.

**Behaviour tests to add (from the delivery and failure rules):**

- A duplicate message does not run a job twice. A message that arrives before `run_at` is refused, and the job still runs on time.
- Crash before the claim, and crash after the claim.
- A job that crashes every worker fails after `max_attempts`.
- A stale worker's finish is rejected (wrong lease token).
- Publishing to a type with no queue is treated as a failed publish.
- Messages wait in their queue when no worker listens, then run when one starts.
- A worker at full concurrency holds at most one unclaimed message per queue; a slow-job flood in one pool does not delay another pool.
- The sweep re-queues a lost job with the growing wait, and does not flood a backlog.
- The same idempotency key at the same moment returns one job.
- Concurrent submits never exceed the active-jobs cap.
- A file belonging to another organisation is rejected at submit; a missing file is rejected.
- A slow storage service does not lengthen the time the organisation lock is held, and does not stall other submits.
- Two tabs refreshing with the same token: the second gets the "already refreshed" answer and the login stays valid; reuse after the window revokes the whole family; refresh is refused after `family_expires_at`.
- Cleaning up old outbox rows does not reset a job's sweep wait.
- With Redis down, refresh still works (fails open) and login is rejected (fails closed).
- **Isolation contract test:** one organisation can never read another's jobs or files through any repository method. This is the condition for relying on application-level isolation instead of row-level security.

How integration tests start their services (throwaway containers from test code, or a shared Compose test profile) is still open and will be settled when versions are pinned.

## 14. API documentation rules

- Every endpoint has its own file: `docs/apis/<endpoint>.md`, covering method, path, path parameters, query parameters, headers, request body, responses, errors, auth needed, scopes, and applicable rate limits, with examples.
- `docs/apis/README.md` is a short list of all endpoints with one line each.
- The docs check (section 13) fails the build when an endpoint has no doc file.
- FastAPI's generated OpenAPI is a secondary reference. The markdown files are the maintained documentation.

**Phase 1 endpoints identified so far** (each needs its own file): signup, login, refresh, logout; create, list and revoke API keys; `POST /v1/files`; `GET /v1/files/{id}` (status and a short-lived download link, needs `files:read`); `POST /v1/jobs`; `GET /v1/jobs` (status filter, keyset pagination); `GET /v1/jobs/{id}`; `GET /v1/jobs/{id}/attempts`; `GET /v1/job-types`; health and metrics.

## 15. Configuration

- Everything required to run (secrets, connection URLs, credentials) is **validated at startup**. A missing or invalid value stops the service immediately, with a clear message. There are no hidden defaults that boot with wrong config. Required values include the JWT signing secret, issuer and audience, and the **public storage URL** used in presigned links (a link signed for an internal Docker host name does not work for outside clients).
- Pure tuning values with a safe default may have defaults in code. The ones identified so far, whose default values still have to be written down: lease length, heartbeat interval, worker concurrency, wait before a delivered message is handed back, sweep wait and cap, sweep batch size, retry delays and max attempts, active-jobs cap, request rate limits, presigned URL lifetime, file size cap, pending-file expiry, job and outbox retention, payload and result size caps, token lifetimes, refresh reuse window, absolute login lifetime (family expiry).
- `WORKER_JOB_TYPES` is **required** for workers. Missing means the worker does not start. `*` means all types it has code for (D39).
- Any fallback must be visible: named, logged, and obvious in the code.

## 16. Security notes

- API key secrets, passwords and tokens are never stored in plain text and never logged.
- Payloads and results may contain sensitive documents. Logs record ids and sizes, not content.
- Files are exchanged through storage references and short-lived presigned URLs, not through the queue. The storage key is generated by the server and namespaced by organisation.
- All inputs are validated against schemas. All queries are scoped by organisation.
- **CSRF (minimum for Phase 1):** `SameSite` cookies plus an origin check on state-changing requests. Bearer tokens in headers are not sent by the browser on their own. Token-based CSRF protection is deferred.
- The refresh cookie is httpOnly, Secure and `SameSite=Strict`, and is sent only to the refresh path. CORS is an explicit allowlist.
- Uploaded files are not scanned for viruses or content in Phase 1.

## 17. Roadmap

| Phase | Scope |
|---|---|
| **0, Foundation** | Repo layout, Compose stack, startup config validation, observability skeleton, CI, docs check, and the verification list in section 18 |
| **1, Core** | Organisations, signup (creates the first organisation) and login with access and refresh tokens, API keys and their Next.js pages, file upload, submit job, job list, status, attempts, result, worker pools, retries, the safety-net sweep, rate limiting (all four limits), `echo` handler plus one real sample handler that uses files and progress, e2e flows, API docs, rate limit docs |
| **2** | Priorities (RabbitMQ priority on each queue), delayed jobs, cancel, completion webhooks, manual retry of a failed job |
| **Deferred (decided, not Phase 1)** | Email verification and the email sender, password reset, member invitations, account recovery, trusted-proxy setting and per-email login limit, idle session limit (the absolute login lifetime is in Phase 1 through the family expiry), password re-entry for key actions, access-token denylist, token-based CSRF, asymmetric JWT signing, failing a job after N failed publishes, maximum wait for a type with no workers, LISTEN/NOTIFY wake-up for the relay, handler version mismatch, multipart upload, virus scanning, organisation and user deletion flow, audit log, billing and usage metering, time partitioning of `jobs`, row-level security, tested down-migrations. The full list with consequences is in the notepad. |
| **Wishlist** | OAuth providers, other queue adapters, per-organisation limit overrides, external workers, SSE |

## 18. Open items

None of these changes the shape of the design.

**Verify in Phase 0, before pinning anything (CLAUDE.md Modules 3 and 5):**

1. Package versions and Python version (including Python 3.14 against FastAPI, SQLAlchemy, asyncpg, Alembic, the RabbitMQ client, OpenTelemetry packages and Next.js). If 3.14 is not supported, either let Postgres generate every id or pin an older Python with a small library for app-side ids.
2. The `postgres:18` image tag and `uuidv7()`.
3. SeaweedFS: presigned PUT and GET, size conditions on upload (presigned POST policy or a size check after upload), and bucket lifecycle rules.
4. RabbitMQ unroutable-message behaviour with the chosen client library.
5. Whether a transaction-level advisory lock works with PgBouncer transaction pooling, and whether PgBouncer is needed in the first version at all.
6. PyJWT and pwdlib (versions, Python support). They are not added until approved.

**Still to settle:**

7. Integration test setup (throwaway containers vs Compose test profile).
8. Default values for the tuning settings in section 15.
9. Which real sample handler ships in Phase 1 (small, exercises files and progress).
10. Whether the access token needs organisation switching when a user belongs to several organisations (Phase 1 signup creates one).

## 19. Known risks

- **At-least-once delivery** means duplicate runs are possible. Mitigation: idempotent handlers as a hard rule, and tests that run each handler twice.
- **No account recovery in Phase 1.** A forgotten password locks the user out, and anyone can sign up with an email address that is not theirs. Accepted for Phase 1 and recorded as deferred.
- **Per-IP login limits do not work behind a proxy** until the trusted-proxy setting exists. Accepted for Phase 1 and recorded as deferred.
- **Redis outage** opens the API request limits (by decision). Mitigation: alert and metric on every fallback.
- **Slow jobs filling every worker.** Mitigation: separate worker pools by job type.
- **One large `jobs` table.** Mitigation: UUIDv7 ordering, the right indexes, and a documented partitioning path.
- **A lost message** after an early ack. Mitigation: the safety-net sweep, with a metric and alert.
- **Operational weight.** The stack has many containers. Mitigation: everything is in one Compose file, and the observability stack can be switched off for light local work.
