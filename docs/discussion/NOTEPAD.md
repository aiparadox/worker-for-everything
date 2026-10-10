# Discussion Notepad

This file is the full memory of the design discussion. A new session should be able to read only this file (plus `CLAUDE.md`, `docs/ARCHITECTURE.md` and `docs/DATABASE.md`) and continue without guessing what was decided, why, what else was considered, or how the parts connect.

Last updated: 2026-10-10 (evening) · Session: `qfe-8-10-2026`

How to read it:

1. **Where we are now** (section 1) tells you the state and the next step.
2. **Decisions in detail** (section 5) has the why, the rejected options and the consequences for each decision.
3. **Wiring map** (section 6) explains how the pieces connect at runtime and in code.
4. **Timeline** (section 4) is the order things happened in, including every question asked and every answer given.

Plain English is required for explanations to the user (`CLAUDE.md`, Module 10). Keep this file in the same style.

---

## 1. Where we are now

| Item | State |
|---|---|
| **Resume here** | After a compaction or in a new session: read this table, then `TODO.md`, then the section "Decisions after the virtual implementation" (D41 to D44) further down. **Do not start implementing anything until the user says so.** The first work is the "Decide first" group in `TODO.md` (tooling choices, the 10 open questions, SQLAlchemy and S3 client choices). Scratch tools used for the virtual implementation (verify scripts, working ledger) are in the session scratchpad, not in the repo, and are not needed to continue. |
| Phase of work | Design finished. The task list is approved and written to `TODO.md` (77 items at first; 85 after the ADR task, the frontend split and the two follow-ups on 2026-10-10, 5 of the first 77 are done: tooling, SQLAlchemy and S3 and test setup, doc updates, supersession notes, ADR list). No product code, no scaffolding, no dependencies installed. |
| Done | Requirements gathered. Design Sections 1, 2 and 3 approved. Rate limiting added. Decisions D1 to D44 recorded. `docs/ARCHITECTURE.md` and `docs/DATABASE.md` rewritten on 2026-10-09 and corrected on 2026-10-10. The virtual implementation (`docs/virtual-implementation/`, 16 files, 40 findings, 172 assumptions) was written and reviewed. |
| Waiting on | Still open from "Decide first" in `TODO.md`: the 10 questions in `docs/virtual-implementation/findings.md` section 6 (deferred by the user until after Phase 0; must be settled before the relay, worker and file API specs) and the tuning defaults (to be proposed inside the config module spec). Decided on 2026-10-10: tooling (D45), SQLAlchemy 2.1 (D46), boto3 (D47), Compose test profile (D48), ADR list (D49). The user said no code yet; the frontend wishes below are still being discussed. |
| Docs state | Both design docs match D19 to D40 as of 2026-10-10. They are drafts until the user approves them. Not pushed to GitHub from this session (no SSH access); the user pushes. |
| Next step | Work the "Decide first" items in `TODO.md` with the user, one decision at a time, and record each answer as a numbered decision (D45 and on). Then, per item: verify the code or setup, write a short spec in `docs/specs/`, get it approved, and only then implement. |
| After that | Per item: verify the code or setup, write a short spec in `docs/specs/`, get approval, then implement on the checked-out branch. |
| Commits | History was rewritten on 2026-10-08 to remove `CLAUDE.md` (user chose option C1). Local commits (newest first): `923a2e7` virtual implementation corrections, `82672ad` virtual implementation, `13a5a2e` verification results, then `53deb26`, `536136f`, `bcc58ce`, `db790a4`, `0544977` (see `git log`). Branch: `master`. **Uncommitted when this note was written:** the D41 to D44 edits to this file and `ARCHITECTURE.md`, and the new `TODO.md`. Check `git status`. The old hashes `d6c8a98` and `80f32a0` no longer exist locally. **The user says they ran the force-push themselves** (the Claude session cannot authenticate to GitHub: `Permission denied (publickey)`), so GitHub should now match; not verified from this session. `CLAUDE.md` stays on disk and is ignored through `.git/info/exclude` (local only). |
| Not created yet | `docs/specs/`, `docs/adr/`, `docs/apis/`, `docs/rate-limits.md`, any code. (`TODO.md` exists since 2026-10-10.) |

### Working rules that shaped this session (from `CLAUDE.md`)

- Ask before acting; never assume (Module 1). Push back when something looks wrong (Module 2).
- Check current sources before recommending, and check package compatibility against locally installed versions, not the latest release (Module 3).
- Required config fails at startup; no hidden defaults; every fallback is explicit, named and logged (Module 4).
- No global installs; ask before adding any dependency (Module 5).
- Fix root causes; for features, build what the real need is (Module 6).
- Workflow: synthesize, present in plain English, get approval, then log in `TODO.md`. One flat checklist with in-place markers `[ ]`, `[o]`, `[x]`. A spec is always written before implementation, and implementation waits for approval of the spec (Module 7).
- Use framework generators for scaffolding; if the target file exists, ask first (Module 8).
- Documentation is `.md` files in the repo, not chat artifacts (Module 9).
- Commits carry no Claude or Anthropic attribution. Branch and merge operations happen only when the user asks (Modules 7 and the commit rules).

## 2. Environment snapshot (checked 2026-10-08)

| Tool | Version found | Note |
|---|---|---|
| Docker | 29.5.2 | |
| Docker Compose | 5.1.3 | |
| Node | 22.18.0 | For the Next.js frontend |
| Python (local) | 3.13.0a5 | An **alpha** build. Do not rely on it. The project's Python version is pinned inside Docker, not taken from this machine. |
| OS and shell | Windows 11, PowerShell and Git Bash | Paths in docs should still use forward slashes |
| Repo | `C:\Users\91930\Documents\github-aiparadox\queue-for-everything` | Git set up by the user. Branch `master`. |

## 3. The original request

The user asked for a queue-based generic server usable for any kind of work, from document processing and OCR pipelines to content generation. Their requirements, in their order:

1. Docker Compose sets up everything needed.
2. Standard, adapter-based code so everything is plug and play. Example given: replace Redis with RabbitMQ later.
3. Unit and integration tests for everything. End-to-end tests for each full flow.
4. Structure: `backend/src`.
5. Every API documented in `docs/apis/<endpoint>.md` with query and path parameters in detail. `docs/apis/README.md` is a short list of all endpoints with a description.
6. PostgreSQL in Docker as the database, and "go for any message broker" (the choice was left to us).
7. Observability, monitoring and logging are a must. A traceable id appears in every log so logs can be unified for analysis.
8. A minimal frontend for authentication. A user can generate an API key to access the APIs. "Dynamic api generation (not static)".
9. It will be used in the real world, at large scale.
10. First deliverable: `docs/ARCHITECTURE.md`.

Added later by the user: keep all decisions and progress in `docs/discussion/NOTEPAD.md` (they forgot to say it in the first message).

## 4. Timeline of the discussion

Everything happened on 2026-10-08. Each row is one exchange.

| Step | What was asked or said | Answer or outcome | Why it mattered |
|---|---|---|---|
| 1 | I classified the work as architectural (new project, no existing code), checked the folder, and asked which language and framework to use. Options offered: TypeScript/NestJS, Python/FastAPI, Go, "recommend one". | **Python (FastAPI).** User also asked for this notepad. | The language decides structure, libraries and the Python version question. |
| 2 | Created the notepad. Asked what "dynamic API generation" means. Options: API keys created at runtime; endpoints generated per job type; both; something else. | **API keys created at runtime by a logged-in user**, "like any real-world platform". | Without this answer the API design could have gone in a very different direction. |
| 3 | Asked how the actual work is defined and run. Options: handler plugins in our workers; external workers over the API; plugins now and external later. | **Handler plugins inside our own workers.** | Defines the core contract of the system (what a job type is). |
| 4 | I searched for evidence on Postgres queues versus brokers, and on the FastAPI, SQLAlchemy, asyncpg, Alembic combination. Then asked which broker to use. Options: RabbitMQ; Postgres queue; Redis Streams. | **RabbitMQ.** | Created the "saved in Postgres but not yet in RabbitMQ" gap, which led to the outbox and relay design. |
| 5 | Asked where files should be stored. Options: MinIO (S3-compatible); local volume; no file handling yet. | **MinIO.** | OCR and document work need files. Jobs pass references, not bytes. |
| 6 | Asked three things together: login method, tenancy, frontend technology. | Login: **email and password for now, but flexible enough to add OAuth providers later.** Tenancy: **organisations with members.** Frontend: **Next.js in `frontend/src`.** (User chose Next.js instead of my two options.) | Login flexibility produced the `AuthProvider` adapter. Organisations shape every table. |
| 7 | Asked which job features go in version one, offering six. The tool allows four options, so I split it and made retries plus dead-letter a default. | User wants priorities, delayed jobs, cancel and webhooks **all eventually, but not at once**: basic system first, then expand, and log the rest. They asked my opinion. On live progress they asked what SSE would add over polling. | I agreed with phasing and said so. I agreed that SSE adds little (see D10 and D11). |
| 8 | Presented design Section 1 (containers, job path, folder layout). Flagged one pushback: the relay as its own container. | User asked me to explain the pushback, and asked for an initial commit. After the explanation: **separate container is fine.** Initial commit `d6c8a98` made. | Confirms the relay design (D12). |
| 9 | Presented design Section 2 (data model, auth, observability, testing). | User raised the **primary key question** (performance matters). I searched, recommended UUIDv7, and asked. User chose **UUIDv7 everywhere.** Then the user approved Section 2. | Led to the Postgres 18 and Python 3.14 questions (D13). |
| 10 | Presented design Section 3 (handlers, delivery, roadmap) and flagged the risk of one organisation starving others. | User: **rate limiting is required** ("I forgot to add it"). I asked where to store counters and what to limit. Answers: **Redis in Docker**, and **all four limits** in phase 1, with **proper documentation**. | New service (Redis), approved by the user. |
| 11 | Asked what the rate limiter does if Redis is down. | **Option 1 for now: open for API limits, closed for login and signup**, and document it. | A fallback must be explicit and documented (CLAUDE.md Module 4). |
| 12 | Wrote `docs/ARCHITECTURE.md`. | Committed as `80f32a0` when the user said "commit everything". | First deliverable done, review pending. |
| 13 | User asked for this notepad to hold the full reasoning, not just decisions. | This rewrite. | Makes cross-session continuation possible without guessing. |
| 14 | User asked for the database plan. | `docs/DATABASE.md` written as a draft, with assumptions A1 to A9 for the user to confirm. | Gave the schema, indexes and operating rules. |
| 15 | User pasted a review from another session. I checked it against the files and searched for the MinIO claim and the partitioning claim. I asked four questions. | Chores: separate `maintenance` container (D19). Storage: **SeaweedFS** (D20). Account scope: **email verification only** in Phase 1, reset and invites deferred (D21). On the requeue design the user asked for a **detailed explanation** before deciding (Q14). | MinIO is archived, which changed D6. The review found six real holes in DATABASE.md. |
| 16 | User asked about "ack after claim" and requeues; I asked four questions (routing, sweep, failed-job re-run, A5); the user interrupted and pasted a large decision pack from several analysis sessions. I analysed it and found eight problems (isolation claim, in-flight messages, no account recovery, proxies, file upload gaps, handler imports, sweep count, lock order). | User answered: account recovery **log and defer**, trusted proxy **log and defer**. Asked me to explain worker pools and items 2, 5 and 8. | See D23 to D35 and "Deferred / later". |
| 17 | User was confused by my word "slot"; I explained it means concurrency. User clarified that concurrency varies per pool (OCR 1, email sending tuned by load testing). | Agreed: dedicated pools through `WORKER_JOB_TYPES`, concurrency per pool, no per-type cap (D35). I then rewrote `ARCHITECTURE.md` and `DATABASE.md` for D19 to D35 and this notepad. | Docs are consistent with the decision pack. |
| 18 | User pasted a second analysis of the committed docs (four problems and several smaller points). I checked each against the files, confirmed all four, and explained three of them on request: the lock held during storage calls, a used refresh token shown again from a second tab, and what the sweep is. The user also asked whether duplicate sweep messages could run a job twice, and whether the outbox keeps finished jobs. | **Apply all recommendations** (D36 to D40), including `family_expires_at` and `GET /v1/files/{id}`. `WORKER_JOB_TYPES` required with `*` ("ok"). | Four real flaws fixed in my own docs. |
| 19 | Docs updated for D36 to D40 and committed. | See the Commits row in section 1. | The notepad's state rows are current again. |
| 20 | User said the design for Phase 1 is done, forbade writing any code, and asked me to verify the remaining items and log requirements before giving me a big task. They confirmed the Claude session cannot reach GitHub because the SSH key has a passphrase. | I verified packages, image tags, npm and upstream documentation (nothing installed or run) and recorded the results in "Phase 0 verification results". Findings that change the design: relay needs `on_return_raises=True`; do not use `aioboto3`; use a presigned POST policy for upload size limits; Redis 8 is AGPLv3 (Valkey is BSD). | The user can now make the five pending choices (Python version, SQLAlchemy version, Redis or Valkey, S3 client, integration test setup). **Not committed yet.** |
| 21 | User gave a large task: build a "virtual implementation" as documentation (overview, one file per part, findings) with strict citation tags, in five phases with gates after phases 1 and 2. | I proposed 14 parts and 8 flows (approved), wrote `overview.md`, 14 part files and `findings.md`, and ran script checks (all tags and cross-references resolve; 172 assumptions registered). Committed as `82672ad`. | The design could now be examined as if it were built. |
| 22 | User pasted a review of that work from another session. | I checked each claim, confirmed the real defects, corrected my own wrong fixes (two), added three missed findings, re-rated four, and committed as `923a2e7`. Result: 40 findings (8 High). I disagreed with one suggestion (a pull loop for consuming; RabbitMQ discourages polling). | Findings are in `docs/virtual-implementation/findings.md`. |
| 23 | User answered the blocking items: Python 3.12, Valkey, development mode, and approved the task list. They asked how the heartbeat works; I explained and proposed a heartbeat thread plus a watchdog that ends the process on timeout (no child process at concurrency 1; not yet a decision). They then said not to start implementing, to update all files and memory, and that they would compact the session. | D41 to D44 recorded; `TODO.md` written (77 items). | Work resumes with the "Decide first" items. |

## 5. Decisions in detail

Each decision lists: what, who decided, why, what was rejected, what it forces elsewhere, and its verification status. "Wiring" means how it connects to other parts.

### D1. Backend is Python with FastAPI

- **Decided by:** the user, from the options TypeScript/NestJS, Python/FastAPI, Go, or "recommend one".
- **Why:** the user chose it. Practical reasons it fits: OCR and AI libraries are Python-first, so handlers can call them directly. FastAPI gives schema validation (Pydantic) and automatic OpenAPI for free.
- **Rejected options:** NestJS (strong structure, but fewer OCR and AI libraries); Go (fast workers, but fewer ready-made OCR and AI libraries and slower to build).
- **Consequences:** the whole `backend/src` tree is Python. Pydantic is used for payload schemas (D4). SQLAlchemy 2 async with asyncpg, and Alembic for migrations, are the expected database stack (the search results describe that combination as well established; not yet pinned).
- **Verification status:** NOT yet pinned. The local Python is 3.13 alpha, so the real version will be set in Docker. See D13 for the Python 3.14 question.

### D2. Keep this notepad

- **Decided by:** the user. Purpose is to make the discussion durable across sessions.

### D3. "Dynamic API generation" means user-created platform API keys

> **Partly superseded.** The "browser session" in the Wiring bullet is replaced by access and refresh JWTs (D32, amended by D37 and D40). The meaning of the decision (user-created keys, hashed, shown once) stands.

- **Decided by:** the user, after I offered three readings.
- **What it means:** a logged-in user creates an API key in the UI at any time. That key is then used to call the platform's APIs, like any real-world platform.
- **Rejected reading:** generating endpoints per job type. Not wanted.
- **How it works (see D7, D8, section 6):** keys belong to an organisation, are stored as a hash, shown once, scoped, expirable and revocable. They are never configured statically in env files.
- **Wiring:** the frontend talks to the API with a browser session. Programs talk to the job APIs with the key. The two credential types are deliberately separate.

### D4. Work runs as handler plugins inside our own workers

- **Decided by:** the user, from "plugins", "external workers" and "plugins now, external later".
- **Why:** simplest thing that still gives a clean contract. We control the worker, the runtime, and dependencies such as OCR libraries.
- **Rejected:** external workers over the API (more flexible but needs worker auth, leases over HTTP and heartbeats up front). Kept as a wishlist item.
- **The contract:** a handler declares a name and version, input and output schemas, timeout, max attempts, retry delays, and a `handle(context, payload)` method. The context provides job id, trace id, organisation, attempt number, storage adapter, `report_progress`, and a logger already tagged with the trace id.
- **Consequences:** payloads are validated at submit time, so bad input fails immediately instead of after queueing. Handlers are registered explicitly in one file. `GET /v1/job-types` lists the types. Handlers must be safe to run twice (D5, section 6).
- **Door left open:** the job lifecycle (claim, heartbeat, complete) is kept clean so external workers could be added later without redesign.

### D5. RabbitMQ is the first broker, behind a `QueueAdapter`

> **History note.** This entry mentions RabbitMQ dead-letter exchanges and delay patterns as reasons for choosing it. Retries no longer use them (D22, D24) and there is no dead-letter queue (D25). RabbitMQ stays the broker, now with one queue per job type (D28). Entry kept as history.

- **Decided by:** the user, from RabbitMQ, a Postgres queue, or Redis Streams.
- **Why RabbitMQ:** real broker from day one. Built-in acknowledgements, dead-letter exchanges, priorities and delay patterns, and a management UI. Fits "will be used at large scale".
- **Evidence consulted:** search results say a Postgres `FOR UPDATE SKIP LOCKED` queue is workable below roughly 1,000 jobs per second, and that above about 10,000 jobs per second a dedicated layer is advised. These came from blog-level sources, so they are rough guidance only, not benchmarks we ran. See section 7.
- **Rejected:** Postgres queue (no extra service and perfectly consistent with job rows, but weaker for very large scale; remains a valid future adapter). Redis Streams (retries, delays and dead-lettering would have to be built by us; durability needs careful setup).
- **Key rule:** the broker only delivers "this job is ready". **Job state and history always live in Postgres.** That is what makes the broker replaceable.
- **Consequence that drove another design piece:** saving a job in Postgres and publishing to RabbitMQ are two separate steps, so a crash between them could lose a job. The answer is the **transactional outbox** plus the **relay** (D12).
- **Verification status:** RabbitMQ client library and RabbitMQ image tag not yet chosen or checked.

### D6. MinIO for file storage, behind a `StorageAdapter`

> **Partly superseded by D20 (2026-10-08).** The `StorageAdapter` and S3-API decision stands. The choice of MinIO as the Docker service does not: MinIO's community edition is archived (see D20).

- **Decided by:** the user, from MinIO, a local volume, or no files yet.
- **Why:** OCR and document jobs involve large files. MinIO speaks the S3 API, so production can use AWS S3 or another S3-compatible store with a config change.
- **Rejected:** local Docker volume (breaks once workers run on more than one machine); no files yet (would force a redesign later).
- **Wiring:** jobs carry file **references**, not bytes. Clients and handlers exchange files through short-lived presigned URLs. Neither the queue nor the database carries file contents.
- **Verification status:** MinIO image and Python client not yet checked.

### D7. Email and password login now, OAuth later, behind an `AuthProvider`

> **Partly superseded.** "Sessions are httpOnly cookies" is replaced by D32: a short-lived access JWT kept in browser memory and a refresh JWT in an httpOnly cookie. The Argon2 library is now chosen in D33 (`pwdlib`, to be approved when installed). The email-verification expectation from D21 was replaced by D30. The `AuthProvider` idea stands.

- **Decided by:** the user. Their words: email and password is good for now, but the system should be flexible enough to handle OAuth from various providers later.
- **Why an adapter:** the login mechanism changes who proves identity but not anything downstream. Putting it behind the `AuthProvider` port means adding Google or GitHub is a new adapter, not a rewrite.
- **Details:** passwords hashed with Argon2 (planned; library not yet chosen). Sessions are httpOnly cookies for the frontend.
- **Rejected:** OAuth only (depends on outside providers from day one and makes local dev and tests harder); both at once (more to build before the first working version).

### D8. Organisations with members

- **Decided by:** the user, accepting my recommendation.
- **Why:** real platforms need teams sooner or later. Adding the concept after data exists means migrating every table.
- **Consequences:** API keys, jobs and usage belong to an **organisation**. A `memberships` table links users to organisations with a role. Every query is scoped by organisation id, so one organisation can never see another's jobs. The rate limits are also per organisation (D17).
- **Rejected:** single-user ownership (simpler now, significant rewrite later).

### D9. Frontend is Next.js in `frontend/src`

> **Partly superseded.** "Using the browser session cookie" is replaced by D32 (access token in memory, refresh cookie). The Next.js version is no longer unchecked: Next.js 16.x needs Node 20.9 or newer (Phase 0 verification results). Frontend requirements added later (admin and user areas, URL-routable state, rendering, skeletons, design rules) are recorded in D50.

- **Decided by:** the user, who chose Next.js instead of my two options (React with Vite, or server-rendered FastAPI pages).
- **Scope:** minimal. Signup, login, list API keys, create key (show once), revoke key.
- **Wiring:** a separate container. It talks to the API like any other client, using the browser session cookie.
- **Verification status:** Next.js version not yet checked. Node 22 is installed locally, but the version used will be pinned in Docker. Scaffolding will use the framework generator (CLAUDE.md Module 8): do not hand-write the skeleton.

### D10. Phase 1 versus Phase 2 job features

> **Partly superseded.** There is no dead-letter queue (D25). RabbitMQ delay queues are not used; delays are the `run_at` time on a new outbox row (D22, D24). The phase split itself stands.

- **Decided by:** the user wants everything eventually, but built in phases, with the later items logged. I agreed that phasing is right.
- **Phase 1:** submit, status and progress by polling, result, retries with backoff, dead-letter queue. Retries and dead-letter were made a default because a queue without them is not usable in the real world.
- **Phase 2:** priorities, delayed or scheduled jobs, cancel, completion webhooks.
- **How Phase 2 stays cheap (important):** the `jobs` table gets `priority`, `run_at` and `cancel_requested` columns from day one even though nothing uses them yet. Adding columns to a large table later is the painful part. The retry backoff mechanism in RabbitMQ (delay queues that dead-letter back) is the same mechanism delayed jobs need.

### D11. No SSE or live streaming

- **Decided by:** the user questioned what SSE adds over polling for a queue system. I agreed.
- **Why:** polling is the baseline for queues. SSE only saves a client from repeating a request. Webhooks (Phase 2) already cover "tell me when it is done". Progress percent is stored in Postgres and visible through `GET /v1/jobs/{id}`.
- **Status:** wishlist only.

### D12. The relay is its own container

- **Decided by:** the user, after I explained the trade-off.
- **The problem it solves:** the API saves a job to Postgres, then something must publish it to RabbitMQ. If the API did both directly, a crash in between would leave a saved job that is never queued (or the reverse).
- **The pattern (transactional outbox):** the API writes the job row and an `outbox` row in **one database transaction**. A separate process, the relay, reads unpublished outbox rows, publishes them to RabbitMQ, and marks them published.
- **Why a separate container instead of a background task in the API:** the relay keeps running when the API restarts, is not slowed by API traffic spikes, and you can run exactly as many relays as you want (a background task per API copy would need locking to avoid duplicates). It is the same image as the API, started with a different command, so it costs one extra line in Compose.
- **Fallback if ever wanted:** the relay logic sits behind the same interface, so it could run inside the API for a simple setup.
- **Also approved in this decision:** the Section 1 design (containers, job path, folder layout) and the rule that `domain/` and `application/` never import from `adapters/`.

### D13. UUIDv7 primary keys everywhere

- **Decided by:** the user, accepting my recommendation. Raised by the user because database performance matters.
- **What:** every table uses the Postgres `uuid` type with `DEFAULT uuidv7()`. The application may also generate the id when it needs it before the insert (for example to create the job and its outbox row together).
- **Why:** UUIDv7 values start with a timestamp, so new rows land at the end of the index like an auto-increment would. Random UUIDv4 scatters inserts across the index, causing page splits and random disk reads. The sources say UUIDv7 performs on par with auto-increment for normal operations. It is also globally unique, so ids can be made anywhere, and not guessable like sequential integers. Time ordering also makes later time-based partitioning and archiving easier.
- **Rejected:**
  - UUIDv4: random, hurts the index.
  - Plain `bigint` auto-increment: smallest and fastest, but ids appear in API URLs, so they are guessable and show volume, and it is awkward if more than one thing generates ids.
  - `bigint` internal plus public UUID: smallest indexes, but two ids on every table and more code everywhere. Only worth it if benchmarks force it later.
- **Costs to remember:** 16 bytes instead of 8, so indexes are somewhat bigger (especially foreign keys such as `job_attempts.job_id` and `outbox.job_id`). A UUIDv7 reveals roughly when the record was created. That is harmless for jobs, and it is why API key secrets are separate and fully random.
- **Dependencies this created:**
  - Native `uuidv7()` needs **PostgreSQL 18**.
  - `uuid.uuid7()` in the Python standard library needs **Python 3.14**. It is not in 3.12.
  - This **replaces my earlier idea of pinning Python 3.12.**
- **Still to verify before pinning:** that FastAPI, SQLAlchemy, asyncpg, Alembic and the other libraries support Python 3.14; that the `postgres:18` Docker tag exists. Fallbacks if 3.14 is not ready: let Postgres generate every id, or pin an older Python plus a small library for app-side ids. The user's selected option allowed either path, as long as UUIDv7 stays.
- **Sources:** section 7.

### D14. Design Section 2 approved

> **Partly superseded.** The "browser session cookie" credential is replaced by access and refresh tokens (D32). The data model changed: `sessions` is gone, `refresh_tokens`, `files` and `job_files` were added (see `DATABASE.md`).

Approved content: the data model, the two credential kinds, the key format, observability, and testing.

- **Data model:** `organisations`, `users`, `memberships`, `api_keys`, `jobs`, `job_attempts`, `outbox`. Idempotency key unique per organisation, so a client that retries after a network error gets the same job back instead of a duplicate.
- **Credentials:** browser session (httpOnly cookie) for the frontend: sign up, log in, manage keys. API key (`Authorization: Bearer`) for programs: job APIs only. They are kept apart on purpose.
- **API key format and handling:** `qfe_<prefix>_<random secret>`. Shown once. Only a hash is stored. Looked up by prefix, compared in constant time. Scopes such as `jobs:read` and `jobs:write`. Optional expiry. Revocable instantly. The secret has no relation to any UUID.
- **Observability:** a trace id (W3C `traceparent`) on every request, generated if the client sends none. Returned in an `X-Trace-Id` header, saved on the job, sent as a RabbitMQ message header, so API, relay and worker log lines for one job share one id. Logs are JSON with `trace_id`, `span_id`, `org_id`, `job_id`. Metrics at `/metrics`. Stack: OpenTelemetry collector, Tempo (traces), Loki (logs), Prometheus (metrics), Grafana (dashboards and alerts). Health at `/healthz` and `/readyz`.
- **Testing:** unit (domain and use cases against in-memory fakes), integration (each adapter against the real service), **contract tests** (one shared suite every implementation of a port must pass; this is what makes replacing RabbitMQ safe), end to end (one test per full flow through the full Compose stack), and a **docs check** that fails when an endpoint has no file in `docs/apis/`.
- **Open at the time:** whether integration tests start throwaway containers from test code or use a shared Compose test profile. Still open (Q10).

### D15. Design Section 3 approved

> **Partly superseded.** Do not use the bullets below as they stand where these differ: "Ack only after the DB commit" is replaced by D23 (ack right after the claim). RabbitMQ delay queues are replaced by D22 and D24. The dead-letter queue is removed by D25. The **state machine** bullet is out of date: a retry goes `running` to `retrying` and is claimed from `retrying`; it never returns to `queued` (see `ARCHITECTURE.md` section 5). The **backpressure** bullet is replaced by per-pool concurrency (D35). What still stands: the roadmap, the handler contract, the lease and heartbeat idea, and the error rules.

- **Handler contract and registration:** see D4.
- **Delivery:** at-least-once. A message is acknowledged only after the worker commits the result to Postgres. A job can therefore occasionally run twice, so **every handler must be safe to run twice** (a hard rule).
- **Leases and heartbeats:** a worker claims a job with a time-limited lease and extends it with heartbeats. If the worker dies, the lease expires and a recovery process requeues the job.
- **Errors:** `PermanentError` (bad input, unsupported file) fails at once, no retries. Anything else, including unexpected exceptions and timeouts, is retried until `max_attempts`. This default is deliberate and must be logged.
- **Retries:** exponential backoff with jitter. (Originally RabbitMQ delay queues; **superseded by D22**: the delay is the `run_at` time on a new outbox row.) After the last attempt the job goes to a dead-letter queue and is marked `failed`. Every attempt is kept in `job_attempts`.
- **State machine:** `queued` to `running` to `succeeded`; or `running` to `retrying` to `queued` until `max_attempts`; or `failed` (permanent error or attempts used up). Phase 2 adds `cancelled`.
- **Backpressure:** worker prefetch is limited so a worker never grabs more than it can run.
- **Roadmap:** Phase 0 foundation, Phase 1 core, Phase 2 extras, plus a wishlist (see section 8).
- **Raised risk that led to D16:** without limits, one organisation could flood the queue and starve everyone else. I had put rate limits on the wishlist; the user moved them into Phase 1.

### D16. Rate limiting is required in Phase 1

> **Partly superseded.** The active-job count is not applied through the `RateLimiter` port; it is counted exactly in Postgres inside the submit transaction (D29). The `RateLimiter` port covers only the request-rate limits. The 429 behaviour stands.

- **Decided by:** the user ("I forgot to add it").
- **Behaviour:** when a limit is hit the API returns `429 Too Many Requests` with a `Retry-After` header and a JSON error body. Normal responses carry rate limit headers so clients can slow down on their own.
- **Wiring:** a `RateLimiter` port like every other technology. Applied in API middleware and in the submit-job use case (for the active job count).

### D17. Redis for rate limit counters; four limits in Phase 1

> **Partly superseded.** The store is Valkey, not Redis (D42); read "Redis" below as Valkey. The "active jobs per organisation" limit is counted in Postgres, not in the store (D29), so only three limits live in Valkey; the fourth request class is refresh and logout (D40). The need for `docs/rate-limits.md` stands.

- **Decided by:** the user approved a **new service (Redis)** and picked all four limits. They noted that all are needed at scale and asked for **proper documentation**.
- **Why Redis:** it is the standard tool for this. Fast, shared across all API copies, and counters expire on their own.
- **Rejected:** Postgres counters (every request would write to the database, on the busiest path, and get worse with traffic); in-memory per API copy (each copy counts separately, so the real limit multiplies with the number of copies; fine only for local dev and tests).
- **Scope:** Redis is used **only for rate limits**, not for the job queue. The queue stays on RabbitMQ.
- **The four limits:**

| Limit | Applies to | Protects against |
|---|---|---|
| Requests per API key | each key | one key hammering the API |
| Requests per organisation | all keys of an organisation together | making many keys to dodge the key limit |
| Active jobs per organisation (queued, retrying or running) | the organisation | one organisation filling the queue and starving others (the fairness protection) |
| Login and signup per IP | unauthenticated auth endpoints | password guessing and fake signups |

- **Documentation required:** a dedicated `docs/rate-limits.md` (every limit, headers, the 429 body, Redis outage behaviour), and each endpoint doc in `docs/apis/` states which limits apply to it.
- **Default values:** not decided. Limit values are configuration with safe defaults (tuning knobs, so code defaults are allowed). Per-organisation overrides are a wishlist extension.

### D18. Redis outage behaviour (explicit fallback)

> **Revised by D29.** The active-jobs cap is now counted in Postgres, so it does not depend on Redis and is not "fail open". The fail-open and fail-closed rules below apply to the three Redis-based limits only.

- **Decided by:** the user chose my recommended option 1 "for now" and asked for it to be documented.
- **Behaviour:**
  - Job and general API limits **fail open**: requests are allowed, with an error log line, a metric and an alert.
  - Login and signup limits **fail closed**: requests are rejected, because without limits they are open to password guessing and fake signups.
- **Why split:** failing closed everywhere turns a Redis outage into a whole-platform outage. Failing open everywhere leaves login unprotected. The split keeps the platform running while protecting the part that is dangerous without limits.
- **Rule from CLAUDE.md Module 4:** the fallback must be visible. The code that applies it lives in one place, is named for what it does, and logs every time it triggers. It must also be written in `docs/rate-limits.md`.
- **The user may revisit this.**

### Review of the drafts by a second session (2026-10-08)

The user ran a separate session that read `NOTEPAD.md`, `ARCHITECTURE.md` and `DATABASE.md` and pasted its review. I checked each point against the files and against current sources before accepting anything (CLAUDE.md Modules 2 and 3). Result:

**Confirmed as real problems in `DATABASE.md` (to be fixed, not yet edited):**

1. **Requeues have no path back into the queue.** The draft allows one outbox row per job. A retry or lease recovery needs a new message. Publishing it straight from the worker brings back the lost-message gap the outbox exists to close. Proposed fix: every requeue writes a new outbox row in the same transaction as the status change. The ERD becomes one-to-many (`jobs ||--o{ outbox`). **Waiting on the user's decision, see Q14.**
2. **A stale worker can overwrite a newer attempt.** Only the claim was guarded. Fix: a lease token on `jobs`; every heartbeat and finish says `WHERE id = ? AND status = 'running' AND lease_token = ?`. Zero rows updated means the lease was lost, so the worker stops. This is what the `lease_lost` outcome is for.
3. **A job that keeps crashing its worker never fails.** Recovery must check `attempts >= max_attempts` and mark the job `failed`, and close the open `job_attempts` row.
4. **Nobody runs the background chores.** Decided in D19.
5. **The active-jobs count can get slow** for an organisation with a huge live backlog. Fix: count with a cap (`SELECT count(*) FROM (SELECT 1 ... LIMIT cap + 1)`), so cost never grows past the cap. The cap value now matters for performance as well as fairness.
6. **Foreign keys missing indexes**, against the doc's own rule: `jobs.api_key_id`, `api_keys.created_by_user_id`, `outbox.job_id`.

**Smaller fixes to make:** password identity should use `user_id` as `provider_subject` (not the email, which can change); never auto-link an OAuth login to an existing user by email unless the provider says the email is verified; CHECK constraint on `api_keys.scopes` against the allowed values; the relay must wait for RabbitMQ publisher confirms before setting `published_at`; drop the promise that publish order equals creation order (UUIDv7 is made at insert, not commit); retention purge must skip rows not in a final state; reword the confusing `result`/`result_ref` check as "at most one is set" and enforce it; `ON DELETE RESTRICT` on `jobs` means an organisation cannot be deleted, so the deletion flow must be described; add `last_seen_at` to `sessions` for idle timeout.

**Gaps in `ARCHITECTURE.md` still to fix:** no CSRF design for cookie sessions; no file-upload entry point (presigned URLs are mentioned but there is no endpoint); trusting proxy headers for the per-IP limits needs a configured trusted-proxy list; the lease token and what a worker does when a message arrives for a job that cannot be claimed (plan: acknowledge it and log it, since the job row says why); section 7 does not list `auth_identities` or `sessions`; **D18 says job limits fail open on a Redis outage, which stops being true once the database counts active jobs (assumption A5)**, so D18 and section 9 need a line change when A5 is accepted.

**Reviewer positions on A1 to A9:** accept A1 to A7 and A9. Accept A8 (no row-level security) only if a contract test proves one organisation can never read another's jobs through any repository method. I agree: cheaper than RLS and catches the same mistake.

**Partitioning by id range:** UUIDv7 is time-ordered, so the primary key `id` can itself be the partition key, which avoids an extra column and keeps foreign keys from `job_attempts` and `outbox` workable. A search supports the general idea (partitioned tables can be referenced by foreign keys since PostgreSQL 12; unique constraints must include the partition key). The idempotency unique rule still has the same problem. Still to verify against the official docs before relying on it.

### D19. Background chores run in a separate `maintenance` container

- **Decided by:** the user, accepting my recommendation.
- **Chores:** lease recovery (including failing jobs that used up their attempts), outbox cleanup, session cleanup, job purge by retention.
- **Why separate from the relay:** a slow cleanup must never delay job publishing. Same image, different command, like the relay (D12).
- **Safety:** several copies may run at once; each chore claims its work with `FOR UPDATE SKIP LOCKED` so copies do not clash.
- **Docs to update:** `ARCHITECTURE.md` section 4 (container table and diagram).

### D20. SeaweedFS replaces MinIO as the Docker storage service

- **Decided by:** the user chose SeaweedFS from SeaweedFS, RustFS, Garage and "decide after I verify".
- **Why the change:** a search found that MinIO stopped publishing Docker images in October 2025, entered maintenance mode on 2025-12-03, was marked no longer maintained on 2026-02-12, and had its repository archived on 2026-04-25. Sources: https://pinggy.io/blog/minio_archived_self_hosted_s3_alternatives/ and https://syncopio.com/blog/minio-maintenance-mode/. The reviewing session had said it was going from memory; the search confirms it.
- **What does not change:** the `StorageAdapter` and the S3 API. Production can still use AWS S3 or any S3-compatible store. Only the Docker service for local use and tests changes.
- **Candidates considered:** SeaweedFS (Apache 2.0, established), RustFS (Apache 2.0, newer, less proven), Garage (simple, but AGPL licence).
- **Condition:** I must verify, before pinning, that SeaweedFS covers what we need through the S3 API (presigned URLs, large and multipart uploads, bucket lifecycle rules for retention). Not yet checked.
- **Docs to update:** `ARCHITECTURE.md` (every MinIO mention) and D6's note.

### D21. Phase 1 account scope: email verification only

> **Superseded by D30 (2026-10-09).** Email verification was later taken out of Phase 1 as well. Password reset and invitations remain deferred. Kept here as history.

- **Decided by:** the user. Email verification is in Phase 1. **Password reset and member invitations are deferred** to a later phase and must be logged as deferred items.
- **My assumption (unchallenged by the user):** signup creates a first organisation automatically, with the new user as `owner`.
- **Consequence not yet decided (Q15):** email verification needs a way to send email. The architecture has no mail service yet. Proposed: an `EmailSender` port with an SMTP adapter, and a local mail catcher container in Compose for development and tests. Needs the user's approval because it adds a service.
- **Schema consequence:** a table for email verification tokens (hashed, expiring, single use). Password reset and invitation tables are not built now.

### D22. Requeues go through new outbox rows with `run_at`; no RabbitMQ delay queues

- **Status: APPROVED by the user ("Let's go with outbox table approach").** History: the user first restated the design only to check their understanding; I wrongly logged it as decided, corrected that, and asked. They then approved explicitly. Supersedes the "RabbitMQ delay queues" part of D15 and `ARCHITECTURE.md` section 11.
- **The rule:** the worker (or the maintenance container's lease recovery) never publishes a retry to RabbitMQ. In **one database transaction** it sets the job status (`retrying`) and inserts a new `outbox` row with `run_at` = the time the job may run again. Only the **relay** publishes, and only rows whose `run_at` has passed.
- **Why:** removes the gap where a job is set to `retrying` but the message is never published. A crash before the commit changes nothing (the lease expires and the maintenance container recovers it). A crash after the commit still leaves the outbox row for the relay.
- **Consequences:** a job can have many outbox rows over its life, so the ERD becomes `jobs ||--o{ outbox`. The same mechanism serves retries, lease recovery and Phase 2 delayed jobs. The broker stays swappable because it needs no delay feature. Delay precision equals the relay's polling interval (about a second). The relay needs a partial index on `run_at` for unpublished rows.
- **Retry numbers (user's stated plan, to be confirmed as defaults):** 3 retries with exponential backoff of 10 seconds, 2 minutes and 10 minutes. Counting the first run, that is `max_attempts = 4`. Delays get random jitter (about ±20%, to confirm). These are per-handler settings with defaults; the exact default values are not yet written in any doc. After the last failure the job becomes `failed` (there is no dead-letter queue, D25).
- **Docs to update:** `ARCHITECTURE.md` sections 5, 11 and 4 (D19), `DATABASE.md` (outbox table, ERD, recovery, indexes), and the review fixes listed above.

## Decision pack of 2026-10-09 (D23 to D35)

The user ran several analysis sessions and pasted the resulting decisions. I checked them against the files and against current sources before writing them down. Where a decision did not do what it claimed, I said so and the user settled it in the conversation. Items marked **refinement** were added by the docs pass to close a gap; the user did not object to them.

### D23. Ack right after the claim

- **Decided by:** the user. Supersedes "ack after DB commit" in D15 and `ARCHITECTURE.md` section 11.
- **Claim:** one transaction: `UPDATE jobs SET status='running', lease_owner=:w, lease_token=:new_random, lease_expires_at=now()+:lease, attempts=attempts+1, started_at=COALESCE(started_at, now()) WHERE id=:id AND status IN ('queued','retrying') AND run_at <= now()`, plus a `job_attempts` insert.
- **Claim succeeded:** commit, **ack**, run the handler. **Claim refused** (finished, owned by someone else, or not due yet): ack and log the reason. Not an error.
- **Crash before the claim commits:** the message was never acked, so RabbitMQ delivers it again; nothing changed in the database. **Crash after:** the lease expires and recovery takes over.
- **All guarded writes:** heartbeat, finish, retry and fail use `WHERE id=? AND status='running' AND lease_token=?`. Zero rows updated means the lease was lost, so the worker stops and the attempt is recorded as `lease_lost`.
- **Why:** RabbitMQ closes a channel when a delivered message stays unacked for more than 30 minutes by default (source in section 7). OCR and generation jobs can run longer. Postgres leases already protect running jobs.
- **Concurrency (D35):** prefetch no longer limits how many jobs run, because acked messages free their place. The worker consumes only while it has free concurrency and cancels its consumers when full.
- **Refinement (wording corrected):** the pack said the worker "never holds a delivered but unstarted message". That cannot be guaranteed: messages already in flight when it cancels still arrive. So a worker may briefly hold **at most one delivered, unclaimed message per queue**. If it cannot start one within a short wait (tuning value), it nacks it with requeue so another worker can take it. The RabbitMQ consumer timeout stays an explicit setting. The pack's instruction to "remove the ack-timeout concern" is therefore only true for running jobs, not for a message waiting for a free place.

### D24. Delay, not timestamp

- **Decided by:** the user. Supersedes the timestamp wording in D22.
- The domain function returns a **duration** with jitter (about 10 seconds, 2 minutes, 10 minutes, ±20%), using the `Clock` port only for tests. SQL writes `run_at = now() + :delay` into both `jobs.run_at` and the new `outbox.run_at` in the same transaction, so they always match (`now()` is one value inside a transaction).
- Why not a timestamp from the app: an app server with a wrong clock would make retries too early or too late. The claim and the relay both compare with the database clock.
- Relay (`outbox.run_at <= now()`) and claim (`jobs.run_at <= now()`) use the same value on the same clock, so a published message is never refused as "too early".
- `jobs.run_at` means "do not run before this time" and is used from Phase 1. `outbox.run_at` is a copy for fast relay lookups. Phase 2 delayed jobs keep the client's absolute time, compared on the database clock.

### D25. No dead-letter queue

- **Decided by:** the user. Supersedes the dead-letter parts of D15 and D22. D5's history stays, marked superseded.
- `jobs.status = 'failed'` plus `job_attempts` is the only failure record. Metric `jobs_failed_total` by job type and error code, and an alert on the failed rate.
- **Unprocessable message** (unknown job id, corrupt body): ack, log an error with the size only (no content), count a metric. The sweep covers the job if one exists.
- **Phase 1 API:** `GET /v1/jobs` with a status filter and keyset pagination, and `GET /v1/jobs/{id}/attempts`. Each needs its own file under `docs/apis/`.
- **Manual retry of a failed job** (`POST /v1/jobs/{id}/retry`) is deferred to Phase 2: it reopens a final state, which touches the state machine, the purge rule and the attempt counter.

### D26. Unknown job type (Rule 1, shrunk)

- **Decided by:** the user. With D28 a worker only consumes queues for types it knows. If a message for an unknown type arrives anyway (misconfiguration): do not claim, ack, log an error, count a metric. The sweep re-queues it.
- Removed from the earlier proposal: the outbox bounce, the 15-minute give-up, and an `unsupported_type` reason.

### D27. Safety-net sweep in `maintenance`

> **Amended by D38.** The sweep's history (`sweep_count`, `last_enqueued_at`) now lives on the `jobs` row instead of being counted from old outbox rows, because outbox cleanup would erase that memory.

- **Decided by:** the user. Needed because after an early ack, a message acked without a claim leaves a job with no owner and no message, and recovery only looks at `running` jobs.
- **Finds:** jobs with `status IN ('queued','retrying')`, `run_at < now() - wait`, no unpublished outbox row, and a newest outbox row older than `wait`.
- **Growing wait:** 5, 10, 20, 40 minutes, capped at 1 hour, each time the same job is re-queued by the sweep. A fixed wait could add a duplicate message for every waiting job every few minutes during a deep backlog, making the backlog worse.
- **Refinement:** count only `reason='sweep'` outbox rows **since the job's last claim**, so a job swept long ago does not keep a long wait.
- A cap on jobs handled per run. One transaction per job, `SKIP LOCKED`. `outbox.reason` column with a CHECK: `submit`, `retry`, `recovery`, `sweep`.
- Indexes: partial `jobs (run_at) WHERE status IN ('queued','retrying')`; `outbox (job_id, created_at DESC)`.
- Every sweep re-queue logs a warning, increments a metric and can alert, because it should be rare and usually means a bug.
- Added to the chores list in `ARCHITECTURE.md` sections 4 and 11 and `DATABASE.md` sections 5 and 10.

### D28. One RabbitMQ queue per job type

- **Decided by:** the user (their words: the per-type queue was agreed). Direct exchange; `outbox.routing_key` is the job type.
- Workers consume only the queues of types they serve. Every process that knows a type (api, relay, worker) idempotently declares that type's durable queue and binding at startup, so a message for a brand-new type has a queue to wait in during a rolling deploy.
- **Publishing:** the relay uses the mandatory flag and publisher confirms. Verified (section 7): RabbitMQ returns an unroutable message **before** it confirms, and without the mandatory flag it would confirm and silently drop it. A returned message counts as a failed publish: `published_at` stays null, and `publish_attempts` and `last_error` are updated.
- **Alerts:** a queue has messages but no consumers; queue depth growing per type (RabbitMQ Prometheus metrics). `job_type` is a safe metric label; `org_id` and `job_id` are not.
- **Benefits:** per-type scaling, safe rolling deploys, and (together with D35 pools) slow jobs that do not block fast ones. Later: priorities through RabbitMQ priority on each queue.
- **Correction recorded:** separate queues alone do **not** stop slow jobs from blocking fast ones, if one worker serves every queue and shares one concurrency limit. Isolation comes from dedicated worker pools (D35).
- **Refinement:** the API and relay must not load heavy handler libraries just to know about a type. So a light **job type definition** (name, version, schemas, retry settings) is separate from the heavy **handler implementation**. Only workers load handlers.
- **Known limits:** a per-type queue is first-in-first-out across all organisations (the active-jobs cap bounds the damage; fair scheduling is wishlist). Removing a type leaves an orphan queue, so a cleanup policy is needed eventually.
- The `QueueAdapter` contract suite must cover "one queue per type" and "an unroutable publish is reported".

### D29. Active-jobs cap counted in Postgres, exact (A5 and A6)

> **Amended by D36.** File checks against storage now happen before the transaction, so the lock is never held during a network call. The order inside the lock is: idempotency key, re-read and lock the file rows, capped count, insert.

- **Decided by:** the user. Supersedes the Redis counter in D17 for this one limit, and revises D18.
- **Capped count** inside the submit transaction: `SELECT count(*) FROM (SELECT 1 FROM jobs WHERE organisation_id=:org AND status IN ('queued','retrying','running') LIMIT :cap+1)`. Cost never grows past the cap. Keep the cap in the low thousands.
- **Exact (A6 amended):** submit takes a per-organisation transaction-level advisory lock, then runs the capped count and the insert. Submits for different organisations do not block each other.
- **Order (refinement):** take the lock; check the idempotency key (return the existing job); check files; capped count; insert; commit. Checking the key before the lock lets two identical requests both pass; counting before the key check could refuse a harmless repeat at the cap.
- If two same-key requests still collide, catch the unique violation and return the existing job.
- **D18 revised:** Redis keeps only the three request-rate limits. API and organisation request limits fail open on a Redis outage; login and signup limits fail closed; the active-jobs cap does not depend on Redis at all.
- Verify in Phase 0: a transaction-level advisory lock with PgBouncer transaction pooling (a session-level lock would not be safe). Test: concurrent submits never exceed the cap. A lock-free, overshoot-tolerant submit is deferred.

### D30. Phase 1 scope trim: no email verification

- **Decided by:** the user. **Supersedes D21.**
- Email verification is out of Phase 1: no `email_verification_tokens` table, no `EmailSender`, no mail-catcher container. Q15 is closed as deferred.
- `users.email_verified_at` stays in the schema and stays empty. The OAuth rule "never link by an unverified email" is kept.
- **Signup accepts any email address** in Phase 1, and creates the user's first organisation automatically, with the user as `owner`. (The organisation auto-creation is now written as decided.)
- **Consequence the user accepted knowingly:** with no verification and no password reset, there is no account recovery in Phase 1 (see Deferred).

### D31. File upload in Phase 1

> **Amended by D36 and D40.** The storage check happens before the transaction (D36). `job_files` now covers input files only, and `jobs.result_file_id` links the result file. `GET /v1/files/{id}` was added so the `files:read` scope has an endpoint (D40).

- **Decided by:** the user. Flow: (a) `POST /v1/files` with file name, size and content type returns a `file_id` and a presigned upload URL; (b) the client uploads straight to storage; (c) the job payload carries the `file_id`; (d) at submit the API checks that the file belongs to the organisation and exists in storage (HEAD), and rejects a bad reference at once; (e) large results are stored as files, and `GET /v1/jobs/{id}` returns a short-lived download URL.
- **`files` table:** id, organisation_id, kind (`input`/`result`), server-generated `storage_key` namespaced by organisation, display name, content type, declared size, status (`pending`/`available`), created_at, expires_at (for unused pending files). `jobs.result_ref` becomes `jobs.result_file_id` referencing `files`.
- Single presigned upload up to a size cap in Phase 1. Multipart is later.
- **Config:** size cap, short presigned URL lifetime, and a **required public storage URL** for presigned links (a link signed for an internal Docker host name does not work for outside clients). A missing value fails at startup (Module 4).
- **New scopes** `files:read` and `files:write`, added to the `api_keys.scopes` CHECK.
- **Refinements closing four gaps found in review:**
  1. A file becomes `available` at the first submit that finds it with a HEAD check. No extra endpoint.
  2. Payloads are free-form, so an input schema declares file fields with a typed `FileRef`. That is how the API finds file ids to check.
  3. A plain presigned PUT does not enforce a maximum size. Use a presigned POST policy with a size range if SeaweedFS supports it, otherwise check the real size after upload. Verify in Phase 0.
  4. A `job_files` link table records which files a job uses, so cleanup never removes a file a queued or retrying job still needs.
- **Retention:** `maintenance` purges unused pending files; used files follow job retention; a bucket lifecycle rule backs it up.
- Each endpoint gets a file under `docs/apis/` listing its rate limits. Verify in Phase 0: SeaweedFS presigned PUT and GET, size conditions, lifecycle rules.

### D32. Login uses access and refresh JWTs

> **Amended by D37 and D40.** A short reuse window stops two browser tabs from logging the user out, and `family_expires_at` gives an absolute login lifetime.

- **Decided by:** the user. Replaces the sessions table and assumption A2, and replaces the "browser session cookie" wording in D14.
- **Access token:** about 15 minutes, signed (PyJWT), held in browser memory, sent as `Authorization: Bearer`. Claims: `iss`, `aud`, `sub`, `exp`, `iat`, `jti`, `org_id`, `role`, `fam`.
- **Refresh token:** also a signed JWT, in an httpOnly, Secure, `SameSite=Strict` cookie scoped to the refresh path. Its own `aud` and `typ: refresh` mean the two types cannot be used in place of each other.
- **Server side:** `refresh_tokens` table keyed by `jti`, with family id, `used_at`, `revoked_at`, `replaced_by`, ip, user agent. Each refresh rotates the token. Reusing a used `jti` revokes the whole family.
- **Logout** revokes the family. The access token stays valid until it expires (accepted). API key management re-reads the user and membership from the database on every call.
- **My note, not an objection:** the `refresh_tokens` table is effectively the old sessions table, so the saving over server-side sessions is small. The pattern is common and the user chose it.

### D33. Auth libraries: PyJWT and pwdlib[argon2]

- **Decided by:** the user. Thin login and refresh code of our own behind the `AuthProvider` port. Frameworks (FastAPI Users, AuthX, Authlib server, external identity servers) were considered and rejected for Phase 1.
- **No dependencies are added yet.** Phase 0 checks versions and Python support, then asks for approval (Modules 3 and 5). Signing secret, issuer and audience are required config that fails at startup. I have not verified either library.

### D34. Database assumptions settled

- **Decided by:** the user. Approved: A1 (text with CHECK for statuses), A3 (three roles), A4 (SHA-256 for API keys, Argon2 for passwords), A7 (no partitioning in Phase 1), A8 (organisation isolation in application code, with a contract test proving one organisation can never read another's jobs or files through any repository method), A9 (no down-migrations in production). A2 is replaced by D32. A5 and A6 are in D29.

### D35. Worker pools and concurrency

> **Amended by D39.** `WORKER_JOB_TYPES` is now a required setting (`*` means all types), not an optional one with a silent fallback. The "if unset, serves every type" wording below is history.

- **Decided by:** the user, after a discussion where I over-used the word "slot" (it just means concurrency). Dedicated pools come from a setting, not automatically from per-type queues.
- `WORKER_JOB_TYPES` lists the job types a worker container serves. It consumes only those queues. If unset, the worker serves every type it has code for, and logs that choice. Startup fails if a listed type does not exist. Run separate containers for separate pools (for example OCR workers on bigger machines).
- **Concurrency is set per pool:** OCR stays at 1 (one heavy job per process; scale by adding containers). Email sending might run higher, tuned after load testing.
- **No per-type cap inside one worker.** It was considered and dropped: it only matters if one process mixes slow and fast types, and pools already avoid that.

## Review round 2 (2026-10-10): D36 to D40

The user ran another analysis session over the committed docs and pasted its findings. I checked each point against the files. All four problems were real and were fixed in `ARCHITECTURE.md` and `DATABASE.md`. The user asked for explanations of three of them first (lock during storage calls, the reuse of a used refresh token, and the sweep and cleanup), then said to apply my recommendations, including both open calls.

### D36. Storage checks happen before the submit transaction (amends D29 and D31)

- **Problem found:** `DATABASE.md` put the storage HEAD checks inside the organisation lock. With 3 files at 200 ms each, an organisation would hold the lock for about 0.6 seconds, limiting it to roughly 2 submits per second, and every waiting submit would tie up a database connection. `ARCHITECTURE.md` already had the better order, so the two docs disagreed.
- **Fix:** check each file against storage and mark it `available` **before** opening the transaction. Inside the transaction, with the lock held: check the idempotency key; re-read the file rows from the database (still `available`, same organisation, not expired) and lock them with `FOR SHARE` so the cleanup job skips them; capped count; insert. The lock lasts a few milliseconds.
- **Accepted edge case:** a file that vanishes from storage between the check and a worker reading it fails that job with a permanent error. Rare.

### D37. Refresh reuse window (amends D32)

- **Problem found:** a used refresh token shown again revokes the whole family. Two browser tabs, or a reload during a refresh, send the same token within moments, so the second request looks like theft and logs the user out for no reason. The earlier session design had a grace period; the JWT design lost it.
- **Meaning of "used":** not time-expired. Refresh tokens are one-time: each refresh swaps the token for a new one and marks the old one used.
- **Fix:** a short reuse window (tuning value, for example 10 to 30 seconds). A used token shown again inside the window gets a distinct "already refreshed" error and nothing is revoked; the browser cookie already holds the new token, so the frontend retries once. The frontend also lets only one tab refresh at a time. A used token shown again after the window revokes the whole family. Test added.
- **Trade-off accepted:** a thief replaying the token inside the window is rejected but not punished.

### D38. Sweep history lives on the job (amends D27)

- **What the sweep is, in plain terms:** a job in Postgres can end up waiting with no message on the way (RabbitMQ lost messages, a bug acked a message without claiming, a message was dropped by a misconfiguration). Nothing would ever run it, and recovery only watches `running` jobs. The sweep, in `maintenance`, periodically finds such jobs and sends a fresh message. It cannot tell a lost message from a slow queue, so it waits longer each time (5, 10, 20, 40 minutes, up to 1 hour) to avoid adding duplicates to an already busy queue.
- **Problem found:** the plan counted earlier `reason='sweep'` outbox rows to know how long to wait, but the cleanup deletes published outbox rows after hours to a day. After a long wait the sweep forgot its history, went back to 5 minutes, and flooded the queue with duplicates.
- **Fix:** two fields on `jobs`, updated in the same transaction as every outbox insert: `sweep_count` (reset to 0 at claim) and `last_enqueued_at`. The sweep finds jobs with `status IN ('queued','retrying')`, `run_at < now() - wait`, `last_enqueued_at < now() - wait`, and no unpublished outbox row, where `wait = 5 min * 2^sweep_count`, capped at 1 hour. Outbox cleanup can delete old rows freely. This also removes the earlier ambiguity about "since its last claim".
- **An outbox row is a message, not a job.** "Done" for an outbox row means published (sent and confirmed), not that the job finished. Published rows are deleted after hours to a day whatever the job's state.
- **Why duplicate messages are harmless:** the claim is one atomic database update that only succeeds if the job is still `queued` or `retrying` and `run_at` has passed. Only one worker wins; the others change zero rows, ack and log. A slow-but-alive worker whose lease expired can still lead to a rare double execution of the handler, which is why handlers must be safe to run twice.
- **Alternative considered:** keep a job's outbox rows until the job is final. Rejected: a long-stuck job would keep a growing pile of rows, and cleanup would need to join against `jobs`.

### D39. `WORKER_JOB_TYPES` is required (amends D35)

- **Decided by:** the user ("ok"). A missing value used to fall back to "serve every type" with a log line. That would let a production OCR pool quietly start serving email jobs and undo the isolation. Module 4 prefers failing at startup.
- **Now:** the setting is required. `*` means all types the worker has code for. Fine in development, a conscious choice elsewhere. Startup also fails if a listed type does not exist.

### D40. Smaller fixes

- **Refresh and logout rate limits:** refresh has its own limit, separate from login, and fails **open** on a Redis outage. Under the login limit (fail closed) a Redis outage would block refreshes and log everyone out. Logout gets a light limit.
- **Same-site deployment rule:** `SameSite=Strict` means frontend and API must be on the same site (for example `app.example.com` and `api.example.com`; different ports on `localhost` are fine). Different registrable domains break login. Alternative: Next.js proxies API calls on its own origin.
- **Absolute login lifetime:** added `refresh_tokens.family_expires_at`, set at login and never extended by rotation. (The idle timeout stays deferred.) This was one of the two calls the user left open; I recommended adding it and the user told me to go ahead.
- **Recovery uses the backoff function:** a job that crashes its worker is not retried at once.
- **One link per file:** `jobs.result_file_id` links result files; `job_files` is for input files only (the `role` column is gone). Both are real foreign keys, so the database refuses to delete a file that is still used.
- **`GET /v1/files/{id}` added** (status and a short-lived download link, needs `files:read`), so the `files:read` scope has an endpoint. This was the other open call; same outcome.
- **Wording:** "four levels of tests plus a docs check"; `last_updated` dates; this notepad's stale state rows.

## Decisions after the virtual implementation (2026-10-10)

The virtual implementation (`docs/virtual-implementation/`) ended with 10 open questions and a list of what blocks starting. The user answered four of the blocking items. The other open questions are still open and are tracked in `docs/virtual-implementation/findings.md` sections 6 and 7.

### D41. Python 3.12

- **Decided by:** the user ("let go with stable 3.12").
- **Why:** stable, and every package checked declares support for 3.12 (section "Phase 0 verification results").
- **Consequences:** `uuid.uuid7()` is not in the 3.12 standard library, so primary keys are generated by Postgres `uuidv7()` (`DEFAULT uuidv7()`), and the application reads the id back with `RETURNING` when it needs it inside a transaction. A small library such as `uuid-utils` is only needed if the application must know an id before the insert. SQLAlchemy 2.1 needs Python 3.11 or newer, so it still fits. The Docker base image is `python:3.12-slim`. This settles D13's open question and V3.

### D42. Valkey instead of Redis; handlers may bring their own store

- **Decided by:** the user ("we are not going for any AI based solution... valkey is fine and handler can have their own redis/valkey depending on its need").
- **What:** the rate limiter store is Valkey (`valkey/valkey:8`), BSD licensed and Redis-compatible, behind the same `RateLimiter` port. The `redis` Python client is expected to work with it (a search said so; not tested). Wherever the design documents say "Redis", read "Valkey".
- **Handlers:** a job handler that needs its own Redis-compatible store may use one. That store belongs to that handler and is not part of the platform. Each such store is a new service and needs approval when a handler needs it (CLAUDE.md Module 5).
- **Open edit:** the word "Redis" is still in many places in `ARCHITECTURE.md`, `DATABASE.md` and the virtual implementation. Replacing it is a task in the task list.

### D43. Development mode: production deployment is not the focus now

- **Decided by:** the user ("we are in development mode right now, don't fixate on production deployment for now").
- **What:** Phase 0 and Phase 1 target a development stack run with Docker Compose. Ingress, TLS, a trusted-proxy setting, backups, secret management and published ports are **not** blocking. They stay on the list as deferred items and become blocking before any real deployment.
- **Still applies:** required configuration still fails at startup, and no secret is hidden as a default (CLAUDE.md Module 4). A development `.env.example` with obviously fake values is fine; real secrets are never committed.
- **Effect on the findings:** F-07 (no ingress or TLS) and the proxy-related parts of F-06 and F-31 are deferred, not dropped.

### D44. Task list approved; implementation not started

- **Decided by:** the user ("approved. Don't start on the implementation yet, just update all your files and memory, and then I will compact the session first. after that we will start.").
- **What:** the task list was approved as presented and written to `TODO.md`: 77 items, in six groups: Decide first (7), Phase 0 foundation (9), Phase 1 core (18), High findings to resolve (7), Phase 2 (5), Deferred (31). All are `[ ]`. The first batch has consecutive-minute IDs (`ISS-20261010-1154` to `WISH-20261010-1310`).
- **Process rule that follows (CLAUDE.md Module 7):** no item starts until its code or setup has been checked, a short spec exists in `docs/specs/`, and the user has approved the spec. Branch and merge actions happen only when the user asks.
- **Findings handling:** the 8 High findings are tracked as their own items (F-07, ingress and TLS, sits inside the deferred production item by D43). The other findings are resolved inside the spec of the part they belong to.

### D45. Python tooling (2026-10-10)

- **Decided by:** the user. They chose `uv` first ("let's use uv for it"), then approved the rest of the proposal ("yes, go with mypy and skip pre-commit and the task runner").
- **What:**

| Need | Choice | Version checked on PyPI 2026-10-10 |
|---|---|---|
| Dependency manager and Python installer | uv (`pyproject.toml`, `uv.lock`, Python 3.12 pinned) | 0.13.0 |
| Linter and formatter | ruff | 0.17.0 |
| Type checker | mypy, strict mode | 2.4.0 (Production/Stable) |
| Tests | pytest, pytest-asyncio, pytest-cov | 9.1.1, 1.4.0, 7.1.0 |
| CI | GitHub Actions (ruff, mypy, unit tests, Docker-based tests) | not applicable |

- **Why mypy and not `ty`:** `ty` (from the makers of uv and ruff) is much faster but still beta (PyPI 0.0.86, "Beta"; stable release targeted for 2026). The project is small, so speed does not matter. Revisit when `ty` is stable.
- **Not chosen:** pyright (needs Node on the backend side); pre-commit hooks (CI runs the same checks; one less thing to install per machine); a task runner such as make or just (make is not available on the user's Windows machine; commands go in the README and CI calls them directly).
- **Still to do:** this approves the plan only. No package is installed. Each dependency is approved again when it is added (CLAUDE.md Module 5), and the exact versions are re-checked against Python 3.12 at that time (`FEAT-20261010-1208`). The frontend lint and format tools come from `create-next-app` and are checked when the frontend is scaffolded.
- **Consequence for the TODO list:** closes `ISS-20261010-1154`. `FEAT-20261010-1201` (repository layout) is no longer blocked by it.

### D46. SQLAlchemy 2.1 (2026-10-10)

- **Decided by:** the user, approving my recommendation.
- **What:** use SQLAlchemy 2.1 (2.1.0 final was released 2026-09-24; PyPI showed 2.1.4 on 2026-10-10; needs Python 3.11 or newer). Fallback: 2.0.54 (maintenance line) if the Phase 0 trial fails.
- **Why:** greenfield project; starting on the maintenance line would force a migration later. The release notes say behaviours changed and upgrades should be tested, and they say nothing about asyncpg, so compatibility with asyncpg 0.32.0, Alembic 1.20.0 and Python 3.12 is **not yet confirmed**.
- **To do:** the trial is part of `FEAT-20261010-1208`. Record the result when it runs. Sources: sqlalchemy.org release post for 2.1.0rc2, docs.sqlalchemy.org/en/21/changelog.

### D47. S3 client: boto3 in a thread pool (2026-10-10)

- **Decided by:** the user, approving my recommendation.
- **What:** the storage adapter uses `boto3` (1.43.111 on 2026-10-10) and runs its blocking calls through `asyncio.to_thread`. Presigned links are computed locally. Only the adapter knows about boto3; the `StorageAdapter` port stays async.
- **Why not aiobotocore (3.9.2):** it pins `botocore>=1.43.101,<1.43.107`, which conflicts with the botocore that boto3 1.43.111 needs, it trails boto3, and it pulls in aiohttp, which nothing else needs. This is consistent with the earlier finding to avoid `aioboto3`.
- **Revisit if:** the thread pool becomes a bottleneck. Only the adapter would change.

### D48. Integration tests start services through a Docker Compose test profile (2026-10-10)

- **Decided by:** the user, approving my recommendation.
- **What:** integration, contract and end-to-end tests run against services started with `docker compose --profile test up -d --wait`. One stack definition is shared by development, CI and tests. No testcontainers dependency (4.15.0 was the current version).
- **Why:** the end-to-end tests need the full stack (api, worker, relay, maintenance) anyway; SeaweedFS has no testcontainers module and would need a duplicate setup.
- **Cost accepted:** someone must start the profile before the tests, and tests must clean up after themselves (for example a fresh database per run). The details go in the test scaffolding spec (`FEAT-20261010-1207`).
- **Revisit if:** fully self-starting adapter tests are wanted; testcontainers could then be added for those only.

### D49. Which decisions get an ADR (2026-10-10)

- **Decided by:** me, on the user's instruction ("it's for you so decide"). The user can still change the list.
- **Rule used (CLAUDE.md Module 7):** an ADR is for an architecture or design decision: a new dependency category, a data-model shift, or a cross-cutting pattern. Tooling choices (D45), library versions (D46, D47) and test setup (D48) do not get one; this notepad is their record.
- **The six ADRs, in `docs/adr/`** (the D numbers are the notepad entries each one summarises; the outbox itself is described across D22 and D23, and the entry that first chose it must be found when the ADR is written):
  1. `0001` Transactional outbox, ack-after-claim, leases and recovery (D22, D23, D24, D27).
  2. `0002` RabbitMQ with one durable queue per job type and no dead-letter queue (D5, D25, D28).
  3. `0003` Ports and adapters, with handlers as plugins inside workers (D4, D5).
  4. `0004` Authentication model: access and refresh JWTs, refresh rotation, hashed API keys (D3, D32, D37, D40).
  5. `0005` Postgres as the source of truth: UUIDv7 keys generated by Postgres, conventions for statuses, times and hashes (D13, D41).
  6. `0006` Choice of external services: SeaweedFS for files, Valkey for rate limits (D17, D20, D42).
- **When they are written:** not all up front. Each ADR is written just before the first spec it affects (Module 7: the ADR comes first and the spec follows it). The content already exists in this notepad, so each one is a short rewrite. Writing them is not yet a task in `TODO.md`; it is proposed to the user.

### D50. Frontend requirements (2026-10-10)

- **Raised by:** the user. Their five points, in my words: (1) two main areas: an admin / platform-admin area and the user-facing area, each possibly with its own sub-areas; the user-facing area is what is being built now; (2) everything URL-routable: pages, components, sections, modals and their state, applied filters; (3) use proper rendering techniques for performance; (4) skeleton loaders, transitions and animation for visual quality; (5) follow standard frontend design principles; plus: research the frontend and give an opinion.
- **Status:** decided on 2026-10-10 by the user's answers to my five questions (below). The points 3 to 5 are guidelines for the frontend spec, not yet detailed.
- **Answers:**
  1. **Admin area:** reserve the structure now (a separate `(admin)` route group with its own layout), build it later. Building it needs a platform-admin role and admin APIs, which do not exist yet.
  2. **Rendering and auth:** keep D32. Logged-in pages fetch data in the browser with the in-memory access token; the static page shell and skeletons come from the server. The backend-for-frontend option was not chosen; revisit it later if server-rendered data becomes important.
  3. **Organisation in the URL:** yes, as the first path segment, but **without a word that says what it is**: `/<org_id>/jobs`, not `/organisations/<org_id>/jobs`. The user's reason: do not advertise that the segment is an organisation id (they said it does not matter for security). Note: ids are UUIDv7 (time-ordered), so the id also shows when the organisation was created; accepted.
  4. **Jobs pages and files pages:** both are wanted in Phase 1, each as its own task.
  5. **Split of the Phase 1 frontend task:** approved (foundation; signup, login and API keys; jobs pages; files pages; admin later).
- **Rules to carry into the frontend spec:** filters, sort, page, tabs and modal open state live in the URL (candidate library `nuqs`, modals as parallel and intercepting routes); the one-time API key and form text never go in a URL; skeletons match the final layout and respect reduced-motion; accessibility target WCAG 2.2 AA; one convention document `docs/FRONTEND.md`. Candidate libraries (not verified, none approved): Tailwind with shadcn/ui, TanStack Query, react-hook-form with zod. Each needs approval before install (Module 5).
- **My main findings (details to be written when decided):**
  - D32 keeps the access token in browser memory, so pages that need the user's data can only be rendered in the browser; server rendering helps only public pages and the page shell. Using Next.js as a backend-for-frontend (it holds the cookie and calls the API) would allow server rendering but reworks the approved auth design.
  - There is no platform-admin role in the data model yet (`memberships` roles are organisation roles). An admin area needs one, plus admin APIs. That ties to finding question 9 (roles and scopes).
  - URL state: filters, tabs, sort, page and modal state belong in the URL; secrets (the one-time API key) and form text must never be.
  - The approved Phase 1 frontend (`FEAT-20261010-1222`) is only signup, login and API keys; these wishes make it much bigger.
- **Still open:** which UI libraries (each needs approval, Module 5), decided in the frontend spec; nothing else. Decided later the same day: users can list files and submit jobs from the UI, but neither is needed for Phase 0. Logged as `FEAT-20261010-1317` (list-files endpoint, with the file API) and `FEAT-20261010-1318` (job submit form, after the jobs pages, job API and files pages).

### D51. Phase 0 specs approved; branch and commit workflow (2026-10-10)

- **Decided by:** the user ("go ahead") after reading the summary of questions for the nine specs in `docs/specs/`. All recommendations were accepted as written: install uv for the current user only; one `qfe` package under `backend/src/`; no Tailwind yet; the whole dependency list in `FEAT-1208` including the beta OpenTelemetry packages; the per-process config table and the tuning starting values (closes `ISS-20261010-1159`); single `grafana/otel-lgtm` container in development and all ports on `127.0.0.1`; Core table definitions with autogenerated migrations and `alembic check`, three migrations; `/readyz` fails only when Postgres is down, `QFE_TELEMETRY=on|off`; `AuthProvider` moves to `FEAT-1218` and the repository interfaces to `FEAT-1211`; the docs file-name rule (`post-v1-jobs.md`); integration tests fail loudly instead of skipping; CI workflow added as `FEAT-20261010-1319`.
- **Order of work:** `1201`, `1208`, `1203`, `1202`, `1204`, `1205`, `1206`, `1207`, `1209`, then `1319` (see `docs/specs/README.md`).
- **Workflow the user set (earlier the same day):** master, then a branch per task named after the item (`feat-<id>-<slug>`), implement with incremental commits, merge locally to master (`--no-ff`, my proposal, accepted by "yes"), next task. I may create, switch and merge branches locally. I delete a branch only after the user has pushed it to origin and told me so (checked with `git branch --merged origin/master`). I never push. Work continues without a question per task, but it stops for: a failure whose root cause is not found, a spec that turns out wrong, a new bug or issue (logged first, Module 7), or any decision needed. Dependencies not on the approved list need a new approval.
- **Documents:** the specs are the record of what was verified and what was not. Each task records its results in this notepad when it ends.

### Result of FEAT-20261010-1201: repository layout (2026-10-10)

- **Built (branch `feat-20261010-1201-repo-layout`):** root `.gitignore`, `.gitattributes` (LF), `README.md` with commands; `backend/` created with `uv init --package --name qfe --python 3.12` (uv 0.13.0, installed for the current user in `C:\Users\91930\.local\bin`; uninstall by deleting `uv.exe`, `uvx.exe` and `uvw.exe` there); the 17 package folders under `backend/src/qfe/`; four test levels with a layout test and three placeholders; tool settings (ruff, mypy strict, pytest) in `backend/pyproject.toml` with `requires-python = ">=3.12,<3.13"`; `frontend/` created with `create-next-app@latest` (flags: `--ts --app --src-dir --eslint --no-tailwind --use-npm --disable-git --no-agents-md`).
- **Frontend packages the generator chose (this is the approved set):** next 16.4.0, react and react-dom 19.3.0, typescript 5.9.3 (not 7), eslint 9.39.5, eslint-config-next 16.4.0, @types/node 20.19.43, @types/react and @types/react-dom 19.3.0. `npm run lint` and `npm run build` pass. This also answers the open question whether Next.js 16.4 works with the TypeScript the generator picks: it picked TypeScript 5.
- **Surprise to remember:** the generator's `next.config.ts` has `cacheComponents: true` and `partialPrefetching: true` switched on by default in Next.js 16.4.0 (I did not pass `--cache-components`). Kept as generated. It changes rules for server components (for example `Date.now()` in a server component fails the prerender). Revisit in `FEAT-1222`.
- **Correction to the spec:** the spec said no Python 3.12 existed on this machine. uv found one installed through pyenv (3.12.2) and uses it; it did not download its own. Any 3.12 works; `.python-version` pins `3.12`.
- **Checks run:** uv resolved Python 3.12.2 and `uv lock` produced `backend/uv.lock` (no packages); all 17 subpackages import under Python 3.12.2 in `backend/.venv`; frontend lint and build pass; `git status` clean, with `.venv`, `node_modules` and `.next` ignored. The pytest, ruff and mypy runs wait for `FEAT-1208`, as the spec says.
- **Note:** git warns that `frontend/package.json` will have CRLF changed to LF (the generator wrote CRLF on Windows); `.gitattributes` handles it.

### Result of FEAT-20261010-1208: dependencies installed and checked (2026-10-10)

- **Built (branch `feat-20261010-1208-dependencies`):** the approved list was added with `uv add` and `uv add --dev`; `backend/uv.lock` pins the result. Everything resolved together on Python 3.12.2 in one go, including the beta OpenTelemetry instrumentation packages (`0.66b1`, pinned exactly with the 1.45.1 SDK line) and SQLAlchemy 2.1.4 with the `asyncio` extra (greenlet 3.5.6).
- **Resolved versions (main ones):** fastapi 0.143.0, starlette 1.7.0, uvicorn 0.54.0, pydantic 2.14.0, pydantic-settings 2.15.0, sqlalchemy 2.1.4, asyncpg 0.32.0, alembic 1.20.0, aio-pika 10.1.0 (aiormq 7.2.1), redis 8.1.0, pyjwt 2.15.1, pwdlib 0.3.1 (argon2-cffi 25.1.0), boto3 1.43.111 (botocore 1.43.111), httpx 0.28.1, structlog 26.1.0, prometheus-client 0.26.0; dev: ruff 0.17.0, mypy 2.4.0, pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0.
- **Version ranges:** uv wrote lower bounds (`>=`) for most packages, not the "compatible release" ranges the spec described. The lock file is what pins the exact versions; upgrades are deliberate (`uv lock --upgrade-package`). Tightening the ranges is possible later and is not needed now.
- **Checks passed:** `ruff check`, `ruff format --check`, `mypy` (strict, 18 files), `pytest` (20 tests). Throwaway checks (not committed): all 23 modules import; a FastAPI route through the Starlette test client with httpx 0.28.1 on Python 3.12; PyJWT encode and decode; pwdlib hash and verify with Argon2id; boto3 builds a presigned POST with a size range (local signing); SQLAlchemy 2.1.4 creates an asyncpg engine. Frontend lint and build already passed in `FEAT-1201`.
- **Found:** Starlette 1.7.0 prints a deprecation warning when its test client runs on `httpx` and asks for `httpx2` instead (PyPI: httpx2 2.13.1, github.com/pydantic/httpx2). `httpx` still works. Logged as `ISS-20261010-1320` for a decision; nothing was added.
- **Still not proven (as the spec said):** SQLAlchemy with a real Postgres (`FEAT-1204`), the `redis` client with Valkey (`FEAT-1205`), boto3 against SeaweedFS (`FEAT-1209`), aio-pika against RabbitMQ (`FEAT-1213`), OpenTelemetry export to a collector (`FEAT-1205`).

### Result of FEAT-20261010-1203: configuration module (2026-10-10)

- **Built (branch `feat-20261010-1203-config`):** `qfe.config` with `base.py` (shared base, URL checks), `settings.py` (`ApiSettings`, `WorkerSettings`, `RelaySettings`, `MaintenanceSettings`, `MigrateSettings`, built from small groups so each process needs only its own), `loader.py` (`load_or_exit`). The root `.env.example` lists every required variable and every tuning variable with its default. 95 tests pass; ruff and mypy (strict, with the pydantic plugin that ships inside pydantic) pass.
- **Behaviour proved by tests:** each required variable is required for each process and named in the error; all problems are printed at once; exit code 2; no secret value appears in errors or in `repr`; empty strings are refused; wrong URL schemes, a JWT secret under 32 characters, `*` or a path in CORS origins, a public storage URL on the same host as the internal one, telemetry `on` without an endpoint, a heartbeat not shorter than the lease, and bad `WORKER_JOB_TYPES` are all refused; the relay starts without JWT, storage or Valkey settings; defaults match the spec; `.env.example` is valid for every process and its tuning lines equal the code defaults (a test fails if they drift).
- **Naming:** the setting called `WORKER_JOB_TYPES` in the design documents is the environment variable `QFE_WORKER_JOB_TYPES` (every variable has the `QFE_` prefix). Same for the migrator role URL: `QFE_MIGRATOR_DATABASE_URL`, separate from `QFE_DATABASE_URL`.
- **Design choices inside the spec:** settings objects are immutable; a hidden `.env` file is never read by the code (`env_file=None`), because the environment (Compose) is the single source; unknown `QFE_` variables are ignored.
- **Not done here:** the "telemetry off" log line (that is `FEAT-1205`), reading secrets from a secret manager (deferred, D43).

### Result of FEAT-20261010-1202: Docker Compose stack (2026-10-10)

- **Built (branch `feat-20261010-1202-compose`):** `compose.yaml` (project name `qfe`), `backend/Dockerfile` (python:3.12-slim, uv 0.13.0 copied from its image, non-root user uid 10001), `frontend/Dockerfile` (node:22-slim, Next.js standalone output, `output: "standalone"` added to `next.config.ts`), `deploy/rabbitmq/rabbitmq.conf` (explicit `consumer_timeout = 1800000`), `deploy/seaweedfs/entrypoint.sh` (writes the S3 identities file from environment variables at start; no secret in the repository), `.env.example` extended, `.env.test.example`, README section.
- **Services and versions actually run:** PostgreSQL 18.6, RabbitMQ 4.3.6 (management and the Prometheus plugin are enabled in the image, which settles that open check), Valkey 8.1.10, SeaweedFS 4.48 (pinned; latest release on GitHub 2026-09-28), Grafana otel-lgtm 0.36.0 (pinned; Grafana 13.2.3 inside), plus the frontend. Only `latest` had been seen before for SeaweedFS.
- **Facts found by running (the spec marked these as not verified):** `weed server -dir=/data -s3 -s3.config=<file> -s3.externalUrl=<url>` is the right one-container command (flags read from `weed server -h`); `-s3.externalUrl` also reads the `S3_EXTERNAL_URL` variable; `weed server -h` also lists `-s3.allowedOrigins` (CORS for browser uploads, to look at in `FEAT-1209` and `FEAT-1221`) and `-s3.autoCreateBucket` (not used: the storage adapter's `ensure_bucket` creates the bucket). The image has `sh`, `wget`, `nc` and `curl`; its default command is `weed mini`. The PostgreSQL 18 image keeps data under `/var/lib/postgresql/18/docker`, so the volume is mounted at `/var/lib/postgresql`.
- **Checks passed:** `docker compose config` for the default, observability and test profiles; the four infrastructure services and the frontend become healthy with `up -d --wait`; from the host: `psql` through the container (PostgreSQL 18.6), the RabbitMQ management API, `valkey-cli ping` (PONG), S3 on 8333 answers 403 without credentials, frontend answers 200; `down -v` then `up` from a clean state works with no manual step; the test profile starts separate copies on 15432, 15673, 16379 and 18333 with data in memory; the observability profile starts Grafana (health `ok`) and OTLP/HTTP on 4318 answers POST-only (GET gives 405); the backend image runs as uid 10001 and imports the app, FastAPI 0.143.0 and SQLAlchemy 2.1.4. All published ports bind to `127.0.0.1`.
- **Changes from the spec, with reasons:** (1) The host port for Postgres defaults to **5433**, not 5432: a PostgreSQL on this machine already listens on 5432 and Docker could not bind it. (2) The frontend host port defaults to **3100**, not 3000: another container on this machine (`open-webui`) holds 3000. The CORS example in `.env.example` follows (`http://localhost:3100`). Both ports can be changed in `.env`. Other containers on this machine (n8n, penpot, open-webui and others) were not touched. (3) `docker compose --profile test up` would also start the development services (services without a profile always start), so the test services are started by name: `docker compose --profile test up -d --wait postgres-test rabbitmq-test valkey-test storage-test`; the README says so. (4) `extends` merges lists, so the test services use `!override` and `!reset` for volumes and ports (Compose feature, checked by `docker compose config`).
- **Not done here, by design:** `migrate`, `api`, `relay`, `worker` and `maintenance` services (added by the tasks that create their entry points); the Postgres init script for roles (`FEAT-1204`); the presigned-link checks (`FEAT-1209`).

### Result of FEAT-20261010-1204: Alembic and the first schema (2026-10-10)

- **D46 confirmed by running it:** SQLAlchemy 2.1.4 with asyncpg 0.32.0 and Alembic 1.20.0, on Python 3.12.2 against PostgreSQL 18.6, work together: upgrade from empty, a second upgrade that changes nothing, `alembic check` reporting no difference between the table definitions and the migrations, and two upgrades started at the same time. The fallback to SQLAlchemy 2.0.54 is not needed.
- **Built (branch `feat-20261010-1204-alembic-schema`):** `qfe/adapters/postgres/tables.py` (11 Core tables, naming convention for constraints and indexes); Alembic set up with its generator (`alembic init --template pyproject_async`, which keeps the Alembic settings in `pyproject.toml` and the logging settings in `alembic.ini`); `migrations/env.py` rewritten to read `QFE_MIGRATOR_DATABASE_URL` through the settings (the placeholder `sqlalchemy.url` the generator writes was removed so nothing can silently use a default), with a session-level advisory lock; three migrations (accounts and auth, files, jobs and outbox) made by autogenerating once and splitting by group; `deploy/postgres/init/01-roles.sh` (creates `qfe_migrator` and `qfe_app`, makes the migrator the owner of the database and the public schema, sets default privileges so the app role can read and write but not change the schema; repeatable); the `migrate` service in `compose.yaml`; for the test service, an extra empty template database `qfe_template` (via `QFE_TEMPLATE_DB`).
- **Tests (22 new, integration against the test service):** all 11 tables appear; repeat upgrade is a no-op; `alembic check` clean; two concurrent upgrades end correctly; ids are `uuidv7` and carry the creation time; the app role can insert, update and delete but cannot create, alter or drop; the migrator can; every allowed job status is accepted and bad ones, bad slugs, bad scopes, negative sizes, bad outbox reasons and attempt outcomes are rejected; a missing parent is rejected; the idempotency key is unique per organisation only; email is unique ignoring case; a file that a job uses cannot be deleted; table settings (`fillfactor` 80, autovacuum values) are present; over all tables: ids are `uuid` with `uuidv7()`, no `timestamp without time zone`, every foreign key column starts an index; a wrong password is refused.
- **Test speed lesson:** on Windows, `localhost` costs about 2 seconds per new connection (it tries `::1` first). The first run of the suite took 171 s. With `127.0.0.1` in `.env.test` and one migrated template database that each test clones, it takes 9 s. Use `127.0.0.1` for anything run on the host.
- **Choices made inside the spec:** extra CHECKs beyond the design text (organisation slug format, text length limits, `trace_id` as 32 lower-case hex, idempotency key length, non-negative sizes and counters); autovacuum starting values 0.02, 1000 and 0.01 (recorded in `DATABASE.md`); the `downgrade()` functions Alembic generated are kept for local use and are not tested (A9). `DATABASE.md` said the `max_attempts` default plan was 4 while the configuration default is 3 (`FEAT-1203`); the document now points to the setting.
- **Found by running:** `docker compose up` reuses an existing image with the same name, so a changed Dockerfile needs `docker compose build` (or `up --build`) first; the one-shot `migrate` container is reported "Healthy" by `up --wait` after it exits with code 0.
- **Not done here:** the repository code and the advisory lock use in the submit transaction (`FEAT-1211`); the advisory lock test under PgBouncer (`WISH-20261010-1310`).

### Deferred / later (decided to postpone, not Phase 1)

These were raised during review of the decision pack (2026-10-09). The user chose to log and defer them. Each has a known consequence, written here so it is a deliberate gap.

| Item | What is deferred | Consequence in Phase 1 | Revisit when |
|---|---|---|---|
| Account recovery under D30 | Any way to recover a forgotten password or an unverified email: no operator reset command, no password reset, no email verification | A user who forgets their password is locked out permanently. Anyone can register an email address that is not theirs and block its real owner. Phase 1 accepts this. | Before real users, or together with the email sender, password reset and OAuth |
| Trusted proxies and per-email login limit | A setting for how many reverse proxies to trust when reading the client IP, and a login limit per email address | Phase 1 ignores forwarded headers and uses the connection's address. **Behind any proxy or load balancer all users then share one address, so the per-IP login and signup limits do not work as intended** (one user's failures can lock out everyone). Only valid for local development or a single direct connection. Must be stated in the rate limit doc. | Before any deployment behind a proxy or load balancer |

**Other deferred items, by area.** Where the user attached a consequence it is stated; the rest are simply not built yet.

*Accounts and login*
- Email verification and the email sender (`EmailSender` port, SMTP adapter, mail-catcher container, a resend-email limit, rules for what an unverified user may do). Phase 1 instead: signup accepts any email. Revisit before OAuth providers, password reset or invitations (D30, supersedes D21).
- Password reset and member invitations (need the email sender).
- The server-side hardened session design that was discussed (one random hashed token with rotation, reuse detection, idle timeout and absolute lifetime). Phase 1 uses access and refresh JWTs (D32).
- Idle session timeout, an "active sessions" view, per-device logout. (The absolute login lifetime is built in Phase 1 through `refresh_tokens.family_expires_at`, D40.)
- Password re-entry before creating or revoking an API key.
- An access-token denylist, to revoke tokens before they expire. Phase 1 accepts the 15-minute window.
- Token-based CSRF protection. Phase 1 has the minimum: `SameSite` cookies plus an origin check on state-changing requests.
- OAuth login providers (Google, GitHub) through the `AuthProvider` port. Authlib is the likely candidate.
- Asymmetric JWT signing and a `kid`. Needed only if other services verify tokens or keys must rotate.

*Jobs and queue*
- Manual retry of a failed job (`POST /v1/jobs/{id}/retry`), Phase 2, needs its own spec.
- Failing a job after N failed publishes. Phase 1 logs, counts and alerts on a stuck outbox row.
- Maximum wait for a type with no workers. Phase 1 only alerts ("queue has messages but no consumers").
- `LISTEN/NOTIFY` wake-up for the relay. Phase 1 polls on a short interval, so a new job can wait about a second.
- Priorities on the per-type queues (RabbitMQ priority), part of Phase 2 priorities.
- Handler version versus `jobs.type_version` mismatch (an old worker running a job made for a newer input schema).
- A lock-free, overshoot-tolerant submit, only if per-organisation lock contention ever becomes a problem.
- Phase 2 features: priorities, delayed jobs, cancel, completion webhooks (`webhook_endpoints` and `webhook_deliveries` tables).
- Per-organisation limit overrides; other queue adapters (Postgres queue, Redis Streams, SQS); external workers; live progress streaming (SSE). The last two are wishlist only.
- Fair scheduling between organisations inside one job type's queue.

*Files*
- Multipart upload for very large files. Phase 1 is a single presigned upload up to a size cap.
- Virus or content scanning of uploads.

*Data and operations*
- Time partitioning of `jobs`: partition by id range (to verify) and move idempotency into its own table.
- Organisation and user deletion flow, and erasing personal data. Intended path: disable, purge jobs after retention, then delete.
- Audit log of user and key actions. Hard to add later without gaps, so it should be decided early even if built later.
- Billing and usage metering.
- Postgres row-level security as a second isolation layer. Phase 1 uses application code plus the contract test (A8).
- Tested down-migrations. Phase 1 uses forward-only migrations (A9).

**Kept in Phase 1 on purpose (so nobody defers them by mistake):** signup creates the user's first organisation; file upload with the `files` table; idempotent submit race handling; logging, metrics and alerts for stuck outbox rows and sweep re-queues; the CSRF minimum; the explicit proxy-header default (documented); the exact active-jobs cap with the advisory lock; the organisation-isolation contract test.

## Phase 0 verification results (2026-10-10)

The user asked for the remaining checks to be done without writing code. Method: package metadata read from PyPI's public JSON, image tags read from Docker Hub's public API, the npm registry, and official or upstream documentation pages. **Nothing was installed or run**, so this proves what packages declare and what documents say, not that they work together at runtime. Real installs and test runs stay in Phase 0, each dependency with the user's approval first (Module 5). Versions are what was current on 2026-10-10 and are not pinned.

### Packages (Python)

Every package below declares support for Python 3.12, 3.13 and 3.14 (classifiers), and the compiled ones publish `cp314` wheels.

| Package | Latest | Needs Python | Note |
|---|---|---|---|
| fastapi | 0.143.0 | >=3.10 | needs starlette>=0.46, pydantic>=2.9 |
| starlette / uvicorn | 1.7.0 / 0.54.0 | >=3.10 | |
| pydantic / pydantic-core / pydantic-settings | 2.14.0 / 2.50.0 / 2.15.0 | >=3.10 | |
| sqlalchemy | 2.1.4 | **>=3.11** | new minor line, see requirements below |
| asyncpg | 0.32.0 | >=3.9 | `cp314` wheels exist |
| alembic | 1.20.0 | >=3.10 | needs SQLAlchemy>=2.0; changelog says 1.19.2 added SQLAlchemy 2.1 support |
| aio-pika / aiormq | 10.1.0 / 7.2.1 | >=3.11 | aio-pika needs aiormq>=7.1.3,<8 |
| redis (client) | 8.1.0 | >=3.10 | works with Redis and Valkey |
| pyjwt | 2.15.1 | >=3.9 | |
| pwdlib (+ argon2 extra) | 0.3.1 | >=3.10 | still a 0.x release; extra pulls argon2-cffi 25.1.0 (last released June 2025) and argon2-cffi-bindings 26.1.0 (`cp314` wheels) |
| boto3 / aiobotocore / aioboto3 | 1.43.111 / 3.9.2 / 15.5.0 | >=3.9 to 3.10 | **version conflict, see requirements below** |
| opentelemetry-api / sdk / exporter-otlp | 1.45.1 | >=3.10 | |
| opentelemetry-instrumentation-fastapi / sqlalchemy / asyncpg | 0.66b1 | >=3.10 | **beta**, pinned exactly to the matching SDK line |
| structlog, prometheus-client | 26.1.0, 0.26.0 | >=3.9 to 3.10 | |
| pytest / pytest-asyncio / testcontainers | 9.1.1 / 1.4.0 / 4.15.0 | >=3.10 | testcontainers is a viable choice for Q10 |
| httpx | 0.28.1 | >=3.8 | **last release Dec 2024; classifier lists only 3.12.** Pure Python, so probably fine on 3.14, but run its tests in Phase 0 (FastAPI's test client uses it) |
| psycopg / uuid-utils / orjson | 3.3.6 / 1.0.0 / 3.13.0 | >=3.10 | optional |

### Frontend and runtime

- `next` 16.4.0 needs Node **>=20.9.0**; peers: React ^18.2 or ^19. React 19.3.0. Local Node 22.18.0 is fine. Docker images `node:22-slim`, `node:24-slim` exist.
- `typescript` latest is 7.0.2 and `eslint` 10.12.0. I did not check whether Next 16.4 supports TypeScript 7. The scaffold must come from the framework generator (`create-next-app`, Module 8), which chooses compatible versions.

### Docker images (all exist)

`postgres:18` and `postgres:18-alpine`; `python:3.14-slim`, `3.13-slim`, `3.12-slim`; `rabbitmq:4-management` (and `3-management`); `redis:8` and `redis:7`; `valkey/valkey:8`; `chrislusf/seaweedfs:latest`; `node:22-slim`, `node:24-slim`; `grafana/grafana`, `grafana/loki`, `grafana/tempo` (last updated 2026-06-02), `prom/prometheus`, `otel/opentelemetry-collector-contrib`; `grafana/otel-lgtm` (an all-in-one Grafana, Loki, Tempo and Prometheus image, updated 2026-10-09, an option for local development); `edoburu/pgbouncer`. No tag is pinned yet.

### Official documentation findings

| Topic | Finding | Source |
|---|---|---|
| `uuidv7()` in Postgres 18 | Exists, signature `uuidv7([shift interval])`, millisecond plus sub-millisecond timestamp plus random. The page does **not** promise ordering within a session or within a millisecond. `uuid_extract_timestamp` and `gen_random_uuid`/`uuidv4` also exist. | https://www.postgresql.org/docs/18/functions-uuid.html |
| `uuid.uuid7()` in Python 3.14 | Exists, added in 3.14; uses a 42-bit counter to keep order within a millisecond. | https://docs.python.org/3.14/library/uuid.html |
| Advisory locks | `pg_advisory_xact_lock(key bigint)` or `(key1 int, key2 int)`; held until the transaction ends, with no manual release. | https://www.postgresql.org/docs/18/functions-admin.html |
| PgBouncer feature map | Session-level advisory locks: **never** in transaction pooling. `LISTEN` and `SET/RESET`: never in transaction pooling. `NOTIFY` works. Prepared statements work in transaction pooling when `max_prepared_statements` is non-zero (supported since PgBouncer 1.21; default 200). The page does not mention transaction-level advisory locks. | https://www.pgbouncer.org/features.html |
| SeaweedFS S3 | Presigned URLs (SigV4), HeadObject, PostObject (POST policy), multipart upload, bucket lifecycle get and put (transition rules not supported) are supported. Replication, website hosting, bucket notifications are not. | https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API |
| SeaweedFS POST policy size limit | The upstream source (`weed/s3api/s3api_object_handlers_postpolicy.go`, master) reads `ContentLengthRange` and returns `EntityTooSmall` or `EntityTooLarge` when the file size is outside it. So a size limit **is enforced**. I did not check whether it is checked before or after the body is read. | https://raw.githubusercontent.com/seaweedfs/seaweedfs/master/weed/s3api/s3api_object_handlers_postpolicy.go |
| SeaweedFS public address | Presigned URLs are signed for a host name and fail when accessed through a different one. Set `weed s3 -s3.externalUrl=https://...` (or pass `X-Forwarded-Host/Proto/Port`). This matches the required "public storage URL" setting in D31. | https://github.com/seaweedfs/seaweedfs/wiki/S3-Configuration |
| aio-pika publish | `Exchange.publish(message, routing_key, *, mandatory=True, immediate=False, timeout=None)`. With confirms on it returns `aiormq.spec.Basic.Ack`. A Nack or Reject raises `DeliveryError`. For an unroutable mandatory message it raises `PublishError` **only if the channel was opened with `on_return_raises=True`**; otherwise it returns the `DeliveredMessage` and calls the channel's return callbacks. The docstring warns a lost confirmation does not mean the broker rejected the message, so retrying can produce duplicates. | https://raw.githubusercontent.com/mosquito/aio-pika/master/aio_pika/exchange.py |
| SQLAlchemy 2.1 | Minimum Python 3.11. `greenlet` is no longer installed by default (use the `[asyncio]` extra). Default PostgreSQL driver is now psycopg 3 (asyncpg still supported). Autoflush now applies to all statements. | https://docs.sqlalchemy.org/en/21/changelog/migration_21.html |
| Alembic | 1.20.0 needs SQLAlchemy>=2.0. 1.19.2 added support for 2.1 accessors; 1.19.0 added Python 3.14 and 3.15 classifiers. | https://alembic.sqlalchemy.org/en/latest/changelog.html |
| Redis licence | Redis 8 ships under **AGPLv3**; Valkey is BSD-3-Clause and wire-compatible, and redis-py works with both. | https://linuxiac.com/welcome-back-to-the-open-source-family-redis/ and https://blog.elest.io/valkey-vs-redis-vs-keydb-which-in-memory-store-after-the-license-change/ |

### Requirements this check produced

1. **Relay must open its RabbitMQ channel with `on_return_raises=True`** (or handle the returned message explicitly). Without it, aio-pika returns the message and does not raise, so an unroutable publish could be mistaken for success. This is the exact failure D28 was written to prevent. The relay must also treat a lost confirmation as "may have been published", which is covered by the at-least-once rule.
2. **Do not use `aioboto3`.** Its latest release pins `aiobotocore[boto3]==2.25.1`, while the current `aiobotocore` is 3.9.2. Also, `aiobotocore` 3.9.2 needs `botocore<1.43.107` while current `boto3` needs `botocore>=1.43.111`, so they cannot be installed together unless pinned through aiobotocore's own `boto3` extra. **Pick one S3 client path** in Phase 0: either `aiobotocore` (async HEAD checks and presigning) or plain `boto3` run in a thread pool. Presigning is local signing with no network call.
3. **SQLAlchemy asyncio needs the `[asyncio]` extra** (greenlet) in 2.1. Use the `asyncpg` driver explicitly, since the 2.1 default is psycopg 3.
4. **Transaction-level advisory lock with PgBouncer:** safe in principle (the lock is released at transaction end and, in transaction pooling, the connection is held for the whole transaction), but PgBouncer's page does not state it. Prove it with an integration test in Phase 0. Session-level locks must never be used. Lock key: derive a 64-bit value from the organisation id (the function takes a `bigint`); a hash collision between two organisations only causes harmless extra waiting.
5. **PgBouncer is not needed in the first version.** If it is added later, set `max_prepared_statements` to a non-zero value (PgBouncer >= 1.21) so asyncpg works in transaction pooling. **A future `LISTEN/NOTIFY` wake-up for the relay (deferred item) cannot go through a transaction-pooled connection**: it needs a direct connection or session pooling.
6. **Public storage URL:** the SeaweedFS S3 gateway must be started with `-s3.externalUrl` (or correct forwarded headers) so presigned links work from outside Docker. This confirms the required config setting from D31.
7. **Upload size limits:** use a presigned **POST policy** with `content-length-range` (SeaweedFS enforces it). A plain presigned PUT does not carry a size limit. Keep the post-upload size check as a second line.
8. **Ordering is not guaranteed:** `uuidv7()` in Postgres 18 documents no ordering guarantee within a millisecond. The design already says nothing may depend on strict order; this keeps that rule.
9. **OpenTelemetry instrumentation packages are beta (`0.66b1`)** and tied to the SDK line `1.45.x`. Pin them together, and expect them to move.
10. **Next.js:** generate the project with `create-next-app` (Module 8) and let it choose the TypeScript and ESLint versions.

### Choices this check puts in front of the user (nothing decided)

> **Update 2026-10-10:** Python 3.12 (D41) and Valkey (D42) are now decided. The SQLAlchemy version, the S3 client and the integration test setup are still open.

- **Python 3.14 or 3.12.** Every package supports 3.14, the `python:3.14-slim` image exists, and 3.14 has `uuid.uuid7()` in the standard library. Recommendation: 3.14. Python 3.12 would work too, with Postgres generating ids (or a small library for app-side ids).
- **SQLAlchemy 2.1 or 2.0.** 2.1 is a new minor line (Python 3.11 minimum, behaviour changes above); Alembic 1.19.2 and later cover it. Staying on 2.0 is the cautious option. Recommendation: decide in the Phase 0 spec after a trial run.
- **Redis or Valkey** for the rate limiter. Both images exist; `redis:8` is AGPLv3, `valkey/valkey:8` is BSD. We use it only as an internal service, so either is workable. Pick by the user's licence policy. The `RateLimiter` adapter is unaffected.
- **S3 client:** `aiobotocore` or `boto3` in a thread pool (requirement 2).
- **Integration tests (Q10):** `testcontainers` 4.15.0 declares Python 3.14 support, so throwaway containers from test code is viable; a shared Compose test profile also works. Not decided.

### Not verified (still open for Phase 0)

- Any runtime behaviour: nothing was installed, built or executed.
- The advisory lock under PgBouncer in practice (requirement 4), httpx on Python 3.14, and `pwdlib` and `PyJWT` behaviour beyond their metadata.
- Whether Next.js 16.4 works with TypeScript 7.
- SeaweedFS presigned PUT and GET end to end from outside Docker, lifecycle expiry behaviour, and whether the POST size check happens before or after the body is read.
- aio-pika's consumer cancel and resume calls and prefetch settings (the API page was not reachable through the fetch tool; only the publish source was read), and RabbitMQ's built-in Prometheus metrics for the "queue has messages but no consumers" alert.
- Compatibility of Grafana, Loki, Tempo, Prometheus and the collector with each other; `grafana/tempo` was last updated 2026-06-02.
- The `consumer_timeout` setting itself (the default of 30 minutes was confirmed earlier in a search, but the broker setting was not read from RabbitMQ's own docs).

## 6. Wiring map (how the pieces connect)

### 6.1 Runtime flow of one job

1. **Client** calls `POST /v1/jobs` with `Authorization: Bearer qfe_...`.
2. **API** (FastAPI): authenticates the key (prefix lookup, constant-time hash compare), checks revoked and expired and scopes, applies the Redis request-rate limits (per key, per organisation), then validates the payload against the registered job type's input schema.
3. **API** first checks each `FileRef` in the payload against storage (HEAD) and marks found files `available`, with no lock held (D36). Then it opens one Postgres transaction: takes the organisation's advisory lock; checks the idempotency key; re-reads and locks the file rows; counts active jobs up to the cap; inserts `jobs` (status `queued`, with `trace_id`, `idempotency_key`, `run_at = now()`), `job_files` and an `outbox` row (`reason = submit`, `routing_key` = job type). Commit. Returns `202` with the job id and `X-Trace-Id`.
4. **Relay** polls for `outbox` rows that are due (`run_at <= now()` and not yet published), publishes each to the queue for its job type with the trace id in the message headers (mandatory flag plus publisher confirms), and marks it published only after a clean confirm. An unroutable message counts as a failed publish.
5. **Worker** (in a pool whose `WORKER_JOB_TYPES` includes the type) receives the message and tries the **claim** (D23): one transaction that sets `running`, takes a lease and a lease token, bumps `attempts`, and writes a `job_attempts` row, only if the job is still waiting and `run_at <= now()`. Claim succeeded: commit, **ack**, run the handler. Claim refused: ack and log. Heartbeats extend the lease. `report_progress` updates the job row.
6. **Success:** one lease-token-guarded transaction saves the result (or result file id) and sets `succeeded`.
7. **Failure (D22):** `PermanentError` marks `failed` and nothing else happens (no dead-letter queue, D25). Anything else, while attempts remain, sets `retrying` and inserts a **new outbox row** with a later `run_at` (backoff with jitter) in the same transaction; the relay publishes it when due. After `max_attempts` the job is `failed`. All worker writes after the claim must match the job's lease token. If a lease expires, the `maintenance` container's lease recovery does the same (fail the job if attempts are used up, otherwise requeue through a new outbox row).
8. **Client** polls `GET /v1/jobs/{id}`.

### 6.2 Where the trace id travels

HTTP header (`traceparent` in, `X-Trace-Id` out) → API logs → `jobs.trace_id` column → outbox row → RabbitMQ message header → relay logs → worker logs → handler logger. One id joins every log line for one job, across all three services.

### 6.3 Code wiring (the adapter rule)

- `domain/` has pure business rules. `application/` has use cases such as SubmitJob and CreateApiKey. Both import **only** from `ports/` (interfaces). They never import from `adapters/`.
- `adapters/` has one folder per technology (`postgres/`, `rabbitmq/`, `s3/`, `redis/`, `password_auth/`). Each implements one or more ports.
- A single wiring (composition) module reads configuration and chooses the adapter for each port. Replacing a technology means writing one new adapter and changing configuration.
- The ports are: `QueueAdapter`, `StorageAdapter`, `RateLimiter`, `AuthProvider`, repositories (`JobRepository` and others), `Clock`, `IdGenerator`.
- Each port has a **contract test suite**. Every adapter for that port must pass it.
- `api/`, `worker/`, `relay/` and `maintenance/` are the four entry points. They share the same image and code, started with different commands.
- `job_types/` holds light job type definitions (name, version, schemas, retry settings) that the API and relay import. `handlers/` holds the heavy implementations that only workers load (D28 refinement).

### 6.4 Docker Compose services

`api`, `worker` (one or more pools, each with `WORKER_JOB_TYPES` and its own concurrency, D35), `relay`, `maintenance` (D19, D27), `frontend`, `postgres` (18), `rabbitmq` (one queue per job type), `redis`, `storage` (SeaweedFS, D20), `otel-collector`, `tempo`, `loki`, `prometheus`, `grafana`. The observability set can be switched off for light local work.

### 6.5 Configuration rules

- Required values (secrets, connection URLs, credentials) are validated at startup. A missing or invalid value stops the service with a clear message. There are no hidden defaults that boot with wrong config.
- Tuning values with a genuinely safe default (timeouts, retry delays, rate limit numbers) may have code defaults.
- Every fallback must be named, logged and obvious in code (Redis outage is the first one).

### 6.6 Docs wiring

`docs/apis/<endpoint>.md` per endpoint (method, path, path parameters, query parameters, headers, body, responses, errors, auth, scopes, applicable rate limits, examples). `docs/apis/README.md` is the short index. `docs/rate-limits.md` is the rate limit reference. A docs-check test fails the build if an endpoint has no doc file. FastAPI's generated OpenAPI is secondary.

## 7. Evidence consulted

These were quick searches, not benchmarks. Treat the numbers as rough guidance. Exact package versions were **not** obtained and must be checked on PyPI and official docs before pinning (CLAUDE.md Module 3).

| Topic | What it said | Source |
|---|---|---|
| Postgres as a queue | `SKIP LOCKED` lets many workers claim different jobs without duplicates. Claims of up to about 30,000 executions per second on one server. Suitable below about 1,000 jobs per second; consider a dedicated layer above about 10,000. A Python library, pgqueuer, exists for this. | https://ecosistemastartup.com/?p=94486 and https://redisson.pro/blog/redis-vs-postgres-when-you-need-both.html |
| FastAPI stack | FastAPI with SQLAlchemy 2 (async), asyncpg and Alembic is a well-established combination. FastAPI supports Python 3.13. The search did not return OpenTelemetry-specific information. | General results (leapcell.io, oneuptime.com and others) |
| UUIDv7 in Postgres 18 | `uuidv7()` is built in. Time-ordered values avoid the page-split problem of UUIDv4. Performance on par with identity columns; 16 bytes versus 8. | https://www.credativ.de/en/blog/postgresql-en/a-deeper-look-at-old-uuidv4-vs-new-uuidv7-in-postgresql-18/ , https://betterstack.com/community/guides/databases/postgresql-18-uuid/ , https://neon.com/postgresql/18/uuidv7-support |
| UUIDv7 in Python | `uuid.uuid7()` was added to the standard library in Python 3.14, not 3.12. | https://blog.openreplay.com/uuid-v4-vs-v7/ and https://forum.djangoproject.com/t/how-to-use-uuidv7-in-python-django-and-postgresql/43474 |
| MinIO status | Stopped shipping Docker images in October 2025, maintenance mode on 2025-12-03, marked no longer maintained on 2026-02-12, repository archived on 2026-04-25. Alternatives: SeaweedFS (Apache 2.0), RustFS (Apache 2.0, newer), Garage (AGPL). | https://pinggy.io/blog/minio_archived_self_hosted_s3_alternatives/ and https://syncopio.com/blog/minio-maintenance-mode/ |
| RabbitMQ ack timeout | A consumer that holds a delivery unacked longer than `consumer_timeout` (default 30 minutes) has its channel closed with PRECONDITION_FAILED. | https://www.netdata.cloud/guides/rabbitmq/rabbitmq-consumer-timeout/ |
| RabbitMQ publisher confirms and unroutable messages | With the mandatory flag and confirms on, an unroutable message is returned (`basic.return`) before the broker confirms; a confirm alone only says the broker accepted the publish, not that a queue received it. | https://www.netdata.cloud/guides/rabbitmq/rabbitmq-publisher-confirms/ |
| One queue per task type | A common pattern: one queue per task type bound to a direct exchange; workers subscribe to the queues for the types they support, so slow jobs in one queue do not block fast jobs in another. | https://lists.rabbitmq.com/pipermail/rabbitmq-discuss/2009-April/003381.html |
| Partitioned tables | Unique and primary key constraints must include all partition key columns; foreign keys can reference partitioned tables since PostgreSQL 12; time-ordered UUIDv7 can serve as a partition key. | https://oneuptime.com/blog/post/2026-08-13-postgresql-mysql-unique-keys-include-partition-key/markdown and https://www.postgresql.org/about/featurematrix/detail/foreign-key-references-for-partitioned-tables |

## 8. Roadmap and wishlist (agreed shape)

| Phase | Scope |
|---|---|
| **0, Foundation** | Repo layout, Compose stack, startup config validation, observability skeleton, CI, docs check |
| **1, Core** | Organisations, signup (creates the first organisation) and login with access and refresh tokens, API keys and their Next.js pages, file upload, submit job, job list, status, attempts, result, worker pools, retries, the safety-net sweep, rate limiting (all four limits) with its docs, `echo` handler plus one real sample handler that uses files and progress, end-to-end flows, API docs |
| **2** | Priorities, delayed jobs, cancel, completion webhooks, manual retry of a failed job |
| **Deferred** | See "Deferred / later" in section 5 |
| **Wishlist** | OAuth providers, other queue adapters (Postgres, Redis), per-organisation limit overrides, time partitioning of `jobs`, external workers, SSE (D11) |

None of these are in `TODO.md` yet. They go there only after the user approves the task inventory (Module 7).

## 9. Opinions and pushbacks I gave

- **Postgres queue could be enough at moderate scale.** I raised it before the user chose RabbitMQ. The user chose RabbitMQ for scale; this is recorded so nobody reopens it without new facts.
- **Relay as a separate container.** I preferred it; the user accepted after the explanation.
- **Phasing the job features and dropping SSE.** I agreed with the user on both.
- **One organisation can starve the others.** I flagged it; the user escalated rate limiting into Phase 1.
- **The Python version changes with UUIDv7.** I said openly that my earlier idea of pinning 3.12 no longer holds if we want app-side `uuid7`.
- **Local Python is an alpha build.** Do not use it as the project's Python.
- **Separate queues do not isolate workloads by themselves.** I pointed out that D23's shared concurrency across queues would let a flood of slow jobs fill every worker; dedicated pools (D35) fix it. The user had already agreed per-type queues; the pool setting was the missing half.
- **Sweep with a fixed wait could flood a backlog.** The user's pack adopted the growing wait.
- **No account recovery in Phase 1 (D30) and per-IP limits behind a proxy.** I flagged both consequences; the user chose to log and defer them.
- **Pack gaps I closed as refinements:** file upload (`available` rule, typed `FileRef`, size enforcement, `job_files`), lock order at submit, light job type definitions, and the wording of what a worker holds while waiting for concurrency.

## 10. Open items

Each has context so it can be settled without re-discovery.

| # | Open item | Why it is open | My leaning |
|---|---|---|---|
| Q10 | Integration tests: throwaway containers started from test code, or a shared Compose test profile | Depends on which library fits the pinned versions. Not checked yet. | Decide when versions are pinned. |
| V1 | Do FastAPI, SQLAlchemy, asyncpg, Alembic, the RabbitMQ client, OpenTelemetry packages and Next.js support the chosen Python and Node versions? | **VERIFIED 2026-10-10 (metadata only).** Every listed package declares support for Python 3.12 to 3.14; Next.js 16.4 needs Node >=20.9. Details in "Phase 0 verification results". | Real installs and test runs still happen in Phase 0, each dependency approved first (Module 5). |
| V2 | Does the `postgres:18` Docker image tag exist and work for our needs? | **VERIFIED:** `postgres:18` and `postgres:18-alpine` exist on Docker Hub; `uuidv7()` is in the Postgres 18 docs. | Pin an exact tag in Phase 0. |
| V3 | Python 3.14 or let Postgres generate every id | **Answerable now:** the whole stack declares 3.14 support, `python:3.14-slim` exists, and 3.14 has `uuid.uuid7()`. | **DECIDED (D41): Python 3.12, ids generated by Postgres.** |
| R1 | Default values for the rate limits and every other tuning setting (lease length, heartbeat interval, worker concurrency, wait before handing back an unstarted message, sweep wait and cap, sweep batch size, retry delays, active-jobs cap, presigned URL lifetime, file size cap, pending-file expiry, retention, payload and result caps, token lifetimes, refresh reuse window, absolute login lifetime) | User has not given numbers. Needs expected traffic. Tuning values may have code defaults (Module 4). | Settle in Phase 0 or the first spec. Pick conservative defaults, configurable by env, and document them. |
| H1 | Which real sample handler ships in Phase 1 (besides `echo`) | Not discussed. | Something small and dependency-light that exercises files and progress, to prove the contract. Ask the user. |
| ~~DB1~~ | **CLOSED.** Assumptions A1 to A9 settled in D29 and D34. | | |
| ~~Q14~~ | **ANSWERED, approved as D22.** | | |
| ~~Q15~~ | **CLOSED, deferred.** Email verification and the email sender are out of Phase 1 (D30). | | |
| ~~Q16~~ | **ANSWERED, D31.** File upload is in Phase 1. | | |
| V4 | Verify before pinning: SeaweedFS presigned PUT and GET, size conditions on upload, lifecycle rules (D20, D31) | **VERIFIED from docs and source (not run):** presigned URLs, HeadObject, POST policy with an enforced size range, multipart and lifecycle are supported; needs `-s3.externalUrl`. | End-to-end test in Phase 0. |
| V5 | Verify: RabbitMQ unroutable-message behaviour with the chosen client library (the broker behaviour itself is confirmed, section 7) | **VERIFIED for aio-pika:** the relay must open its channel with `on_return_raises=True`, otherwise an unroutable publish is returned, not raised. | Cover it in the `QueueAdapter` contract test. |
| V6 | Verify: a transaction-level advisory lock with PgBouncer transaction pooling, and whether PgBouncer is needed at all (D29) | **PARTLY VERIFIED:** transaction-level locks are released at transaction end (Postgres docs); PgBouncer docs cover only session-level locks (never work in transaction pooling) and do not mention transaction-level ones. PgBouncer is not needed in the first version. | Integration test in Phase 0. |
| V7 | Verify: PyJWT and pwdlib versions and Python support (D33). Not added until approved (Module 5). | **VERIFIED (metadata):** PyJWT 2.15.1 and pwdlib 0.3.1 (a 0.x release) declare Python 3.14 support; the argon2 extra uses argon2-cffi 25.1.0 with `cp314` wheels in its bindings. | Behaviour test in Phase 0. |
| O1 | Does the access token need organisation switching when a user belongs to several organisations? | Phase 1 signup creates one organisation, so not needed yet. | Decide when invitations arrive. |
| DB2 | Audit log and billing or usage metering | Deferred (listed in "Deferred / later"). An audit log is hard to add later without gaps. | Decide early even if built later. |
| T1 | Task inventory for `TODO.md` | The user has not yet approved the rewritten `ARCHITECTURE.md` and `DATABASE.md`. | Present the inventory after the user approves both docs. |

## 11. Assumptions made (not confirmed by the user)

These are in `docs/ARCHITECTURE.md` and should be challenged if wrong:

- Argon2 for password hashing (a standard recommendation; library not chosen).
- Pydantic for handler schemas (comes with FastAPI).
- A `/v1` URL prefix for the API.
- Job submit returns `202 Accepted`.
- Scopes named `jobs:read`, `jobs:write`, `files:read` and `files:write`.
- `/v1/files`, `/v1/jobs`, `/v1/jobs/{id}`, `/v1/jobs/{id}/attempts` and `/v1/job-types` as endpoint paths (the first four come from the decision pack; `/v1/job-types` is mine).
- The observability stack names (Tempo, Loki, Prometheus, Grafana) were approved as part of Section 2, but their exact images and versions are not chosen.
- The API key prefix format `qfe_` (short for queue-for-everything) is a placeholder.

## 12. Glossary (plain English)

- **Adapter / port:** a port is an agreed shape for talking to a technology (for example "queue"). An adapter is the code that does it with a specific technology (for example RabbitMQ). Swap the adapter, keep the rest.
- **Outbox:** a table where "please publish this message" is saved in the same database transaction as the job, so nothing is lost between saving and publishing.
- **Relay:** the small program that reads the outbox and publishes to RabbitMQ.
- **Lease and heartbeat:** a worker's time-limited claim on a job, renewed regularly while it works. If the worker dies, the claim runs out and the job is handed to another worker.
- **At-least-once delivery:** a job may run more than once, but is never silently lost. So handlers must be safe to repeat.
- **Idempotent:** doing it twice has the same effect as doing it once.
- **Dead-letter queue:** where a message would go after all retries fail. **Not used in this project** (D25); failures are read from the database.
- **Claim:** the worker's database update "this job is mine". It only works if the job is still waiting and its `run_at` has passed.
- **Lease:** the time-limited ownership written at claim time.
- **Lease token:** a random code written at claim time. Heartbeat, finish, retry and fail writes must present it, so a worker that lost its lease cannot overwrite a newer attempt.
- **Heartbeat:** the worker extending its lease while it works.
- **Recovery:** the `maintenance` container handling jobs whose lease ran out.
- **Ack:** telling RabbitMQ to forget a message. This project acks right after the claim (D23).
- **Sweep:** the safety-net check in `maintenance` that re-queues jobs that are waiting with no message on the way (D27).
- **Concurrency:** how many jobs one worker process runs at the same time. Set per worker pool (D35). (I earlier called this a "slot"; that word is not used any more.)
- **Worker pool:** a group of worker containers serving the same job types, set with `WORKER_JOB_TYPES`.
- **Per-type queue:** one RabbitMQ queue for each job type (D28).
- **Outbox row:** one message waiting to be sent (or already sent) to RabbitMQ. It is not a job. "Done" means published, not that the job finished.
- **Reuse window:** a short time (for example 20 seconds) in which a refresh token that was already used can be shown again without logging the user out. It covers two browser tabs refreshing at once (D37).
- **Token family:** all refresh tokens that descend from one login. Revoking the family ends that login.
- **Family expiry:** the absolute end of a login, set once and never extended by refreshing (D40).
- **Mandatory publish:** publishing with a flag that makes RabbitMQ return a message it cannot route to any queue, instead of silently dropping it.
- **Presigned URL:** a temporary link that lets a client upload or download one file directly to or from storage.
- **Job type definition vs handler:** the definition is the light description of a job type (name, schemas, retry settings); the handler is the code that does the work.
- **Contract test:** one test suite that every implementation of a port must pass, proving they behave the same.
- **UUIDv7:** a unique id that starts with a timestamp, so new ids sort in creation order (good for database indexes).
- **Fail open / fail closed:** when a safety check breaks, either allow the action (open) or block it (closed).
