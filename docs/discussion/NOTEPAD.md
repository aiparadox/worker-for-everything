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
- Q9: Observability stack: proposal to be reviewed in the design (OpenTelemetry, Prometheus, Grafana, Loki, Tempo).

## Progress

- 2026-10-08: Project folder checked. It only holds `CLAUDE.md`. Docker 29.5.2, Compose 5.1.3, Node 22.18 and Python 3.13.0a5 are installed.
- 2026-10-08: Stack chosen (D1). Next step is to settle the open questions, then write `docs/ARCHITECTURE.md`.
