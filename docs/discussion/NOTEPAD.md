# Discussion Notepad

Running log of decisions, open questions and progress while we design the project. Newest entries go at the bottom of each section.

Last updated: 2026-10-08

---

## Goal (from the user's first message)

A generic, queue-based server for any kind of work (document processing, OCR pipelines, content generation). Meant for real-world, large-scale use.

## Requirements given

- Docker Compose sets up everything.
- Adapter-based code so parts can be swapped (for example Redis for RabbitMQ).
- Unit and integration tests for everything. End-to-end tests for each full flow.
- Code lives under `backend/src`.
- Every API documented in `docs/apis/<endpoint>.md` (query and path parameters in detail). `docs/apis/README.md` is a short list of all endpoints with a one-line description.
- PostgreSQL in Docker as the database. A message broker is still to be chosen.
- Observability, monitoring and logging are required. A trace ID goes into every log line so logs can be joined for analysis.
- Minimal frontend for authentication. A user can create an API key to call the APIs. Keys are created dynamically at runtime, not set in static config.
- First deliverable: `docs/ARCHITECTURE.md`.

## Decisions

| # | Decision | Date | Notes |
|---|----------|------|-------|
| D1 | Backend language and framework: **Python with FastAPI** | 2026-10-08 | Local Python is 3.13 alpha, so Docker should pin a stable version. Versions to be checked against current docs before we commit to them. |
| D2 | Keep discussion notes in this file | 2026-10-08 | Requested by the user. |
| D4 | Work runs as **handler plugins inside our own workers**. Each job type is a Python handler registered by name; clients send `{type, payload}` | 2026-10-08 | Job lifecycle (claim, heartbeat, complete) should stay clean enough that external workers could be added later, but that is not in scope now. |
| D5 | First broker implementation: **RabbitMQ**, behind a `QueueAdapter` | 2026-10-08 | Job state and history always live in Postgres; the broker only delivers "job ready" messages. Because a job is saved in Postgres and published to RabbitMQ separately, the doc must cover the lost-message risk between the two (planned answer: transactional outbox). Package versions to be checked on PyPI before pinning. |
| D6 | File storage: **MinIO (S3-compatible)** in Docker, behind a `StorageAdapter` | 2026-10-08 | Jobs carry file references, not file bytes. Production can use AWS S3 or another S3-compatible store. |
| D7 | Login: **email and password** for now. The auth code must be flexible so OAuth providers can be added later | 2026-10-08 | Means an `AuthProvider` adapter (password first, OAuth providers later). Passwords hashed (Argon2 planned). |
| D8 | Tenancy: **organisations with members**. API keys, jobs and usage belong to an organisation | 2026-10-08 | Avoids a painful data migration later. |
| D9 | Frontend: **Next.js**, in `frontend/src` | 2026-10-08 | Scope stays minimal: signup, login, API key list, create key, revoke key. Version to be checked against current docs. |
| D10 | **Phase 1 job features:** submit job, status and progress via polling, result, retries with backoff, dead-letter queue. **Phase 2 (all wanted, built after the basic system works):** priorities, delayed/scheduled jobs, cancel, completion webhooks | 2026-10-08 | Phase 1 schema and queue design must leave room for the Phase 2 fields (`priority`, `run_at`, `cancel_requested`) so Phase 2 needs no rewrite. |
| D11 | **No SSE / live streaming.** Polling is the baseline; webhooks (Phase 2) cover push notification | 2026-10-08 | Kept only as a wishlist idea. |
| D12 | **Section 1 of the design approved** (containers, job path, folder layout). The outbox relay runs as its **own container** (same image, different command) | 2026-10-08 | Reason: it keeps publishing when the API restarts and scales on its own. Rule: `domain/` and `application/` never import from `adapters/`. |
| D13 | **Primary keys: UUIDv7 on every table**, using the Postgres `uuid` type with `DEFAULT uuidv7()`. The app may also generate ids when it needs one before insert | 2026-10-08 | Needs **PostgreSQL 18** (native `uuidv7()`) and, for app-side generation, **Python 3.14** (`uuid.uuid7()` in stdlib). This replaces the earlier idea of pinning Python 3.12. TO VERIFY before pinning: FastAPI, SQLAlchemy, asyncpg etc. support Python 3.14, and the `postgres:18` Docker tag exists. API key secrets stay separate and fully random. Rejected: UUIDv4 (random inserts hurt the index), plain bigint (guessable ids), bigint plus public UUID (two ids everywhere). |
| D14 | **Section 2 of the design approved**: data model (organisations, users, memberships, api_keys, jobs, job_attempts, outbox), browser session vs API key credentials, key shown once and stored hashed, trace ID end to end, OpenTelemetry + Tempo + Loki + Prometheus + Grafana, four test levels plus adapter contract tests and a docs-coverage test | 2026-10-08 | Q9 (observability stack) is settled by this approval. Q10 (integration test containers) is still open. |
| D15 | **Section 3 of the design approved** (handler contract with Pydantic input/output schemas and explicit registration, at-least-once delivery with idempotent handlers, ack after DB commit, leases and heartbeats, PermanentError vs retryable errors, exponential backoff with jitter, dead-letter queue, roadmap phases 0 to 2 plus wishlist) | 2026-10-08 | One change requested: see D16. |
| D16 | **Rate limiting is required in Phase 1** (moved up from the wishlist). Returns 429 with `Retry-After` | 2026-10-08 | Storage and what is limited are still to be decided (Q11, Q12). It must sit behind a `RateLimiter` adapter like everything else. |
| D17 | Rate limit counters live in **Redis** (new Docker service, approved), behind a `RateLimiter` adapter. Redis is used only for limits, not for the job queue. **All four limits are in Phase 1**: requests per API key, requests per organisation, max waiting + running jobs per organisation, and a stricter per-IP limit on login and signup | 2026-10-08 | The user asked for **proper documentation** of rate limiting: a dedicated doc, plus every endpoint doc lists its limits and the 429 / `Retry-After` / rate limit headers behaviour. |
| D18 | **Redis outage behaviour:** job and general API limits **fail open** (requests allowed, with an error log line, a metric and an alert); login and signup limits **fail closed** (requests rejected) | 2026-10-08 | "For now": the user may revisit later. Must be documented in the rate limit doc and in the code where the fallback triggers (explicit, per CLAUDE.md Module 4). |
| D3 | "Dynamic API generation" means platform API keys: a logged-in user creates keys at runtime and uses them to call the platform APIs, like any real-world platform | 2026-10-08 | Not per-job-type endpoint generation. Keys stored hashed, revocable. |

## Open questions

- ~~Q1~~: Answered, see D5.
- ~~Q2~~: Answered, see D4. The detailed handler contract still goes in the architecture doc.
- ~~Q3~~: Answered, see D3.
- ~~Q4~~: Answered, see D9.
- ~~Q5~~: Answered, see D7.
- ~~Q6~~: Answered, see D8.
- ~~Q7~~: Answered, see D6.
- ~~Q8~~: Answered, see D10 and D11.
- ~~Q11~~, ~~Q12~~: Answered, see D17.
- ~~Q13~~: Answered, see D18.
- Q10: Integration tests: throwaway containers started by test code vs a shared Compose test profile (to verify against pinned versions).
- ~~Q9~~: Answered, see D14.

## Progress

- 2026-10-08: Project folder checked. It only holds `CLAUDE.md`. Docker 29.5.2, Compose 5.1.3, Node 22.18 and Python 3.13.0a5 are installed.
- 2026-10-08: Stack chosen (D1). Next step is to settle the open questions, then write `docs/ARCHITECTURE.md`.
- 2026-10-08: Initial commit made (`d6c8a98`). Design Sections 1 to 3 approved (D12, D14, D15), rate limiting added (D16 to D18).
- 2026-10-08: `docs/ARCHITECTURE.md` drafted and waiting for the user's review. Still open: Q10 (integration test setup), default rate limit values, which sample handler ships in Phase 1, version pinning checks (Python 3.14 support, `postgres:18` tag).
- Next: user reviews the architecture doc, then the task inventory is presented for approval before anything is logged in `TODO.md`.
