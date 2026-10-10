# TODO

One flat checklist. Status is the marker only: `[ ]` Todo, `[o]` In-Progress, `[x]` Done. Items never move; a finished item gets its completion time at the end of its line. Format: `- [<status>] <ID> — <description>`.

IDs are `<PREFIX>-YYYYMMDD-HHMM`. The first batch (the whole approved task list of 2026-10-10) was created at once, so its IDs use consecutive minutes starting at 2026-10-10 11:54 to stay unique; they are labels and may be ahead of the clock. Prefixes: FEAT planned functionality, ISS general issue or decision, WISH deferred or wishlist idea.

Approved by the user on 2026-10-10. **Nothing is implemented yet.** Before any item is started: verify the code or setup it touches, write a short spec in `docs/specs/`, get the spec approved, then change the item to `[o]` (CLAUDE.md Module 7). Context for the items is in `docs/discussion/NOTEPAD.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md` and `docs/virtual-implementation/`.

## Decide first

- [x] ISS-20261010-1154 — Decide the Python tooling: dependency manager (for example uv, pip-tools or poetry), linter and formatter, type checker, and the CI tool. Blocks scaffolding. Decided as D45: uv, ruff, mypy strict, pytest with pytest-asyncio and pytest-cov, GitHub Actions; no pre-commit, no task runner. [2026-10-10 12:13]
- [ ] ISS-20261010-1155 — Settle the 10 open questions in docs/virtual-implementation/findings.md section 6 into numbered decisions in NOTEPAD.md: handler execution and shutdown, connections, result files, repeated submits, delivery settings, retention and file cleanup, roles and scopes, poison outbox rows, load numbers. Ingress and TLS are deferred by D43. Deferred by the user until after the initial setup (Phase 0): it must be settled before the specs for the relay (FEAT-20261010-1215), the worker (FEAT-20261010-1216) and the file API (FEAT-20261010-1221). When answered, update the design docs for the answers.
- [x] ISS-20261010-1156 — Choose SQLAlchemy 2.1 or 2.0 after a trial run, the S3 client path (aiobotocore or boto3 in a thread pool), and how integration tests start services (testcontainers or a Compose test profile). Decided as D46 to D48: SQLAlchemy 2.1 (2.0.54 as fallback, trial in FEAT-20261010-1208), boto3 in a thread pool, Compose test profile. [2026-10-10 12:25]
- [x] ISS-20261010-1157 — Update ARCHITECTURE.md, DATABASE.md and the docs/virtual-implementation files for D41 to D43 (Python 3.12, Valkey instead of Redis, development stage) and for the answers to ISS-20261010-1155. Done for D41 to D48 (Redis replaced by Valkey in 64 lines, Python 3.12, SQLAlchemy 2.1, boto3, Compose test profile); findings.md carries a note instead of edits because it records the review as written. The part for the answers to ISS-20261010-1155 moved into that item. [2026-10-10 12:41]
- [x] ISS-20261010-1158 — Add the missing supersession notes in NOTEPAD.md for D3, D7, D9, D10, D16 and D17, and correct the note on D15 (finding F-30). [2026-10-10 12:41]
- [x] ISS-20261010-1159 — Write default values for all tuning settings (lease length, heartbeat interval, concurrency per pool, retry delays, caps, rate limits, retention, token lifetimes, refresh reuse window) once the load numbers or a development profile are agreed. Done as the development starting values in section 3.5 of docs/specs/FEAT-20261010-1203-config.md, approved 2026-10-10; to be tuned with real numbers later. [2026-10-10 13:14]
- [x] ISS-20261010-1200 — Decide which decisions need an ADR in docs/adr/ (CLAUDE.md Module 7), for example the transactional outbox, RabbitMQ per-type queues, UUIDv7 keys and Valkey. Decided as D49: six ADRs (outbox and delivery, RabbitMQ per-type queues, ports and adapters, auth model, Postgres conventions, external services). [2026-10-10 12:30]
- [ ] FEAT-20261010-1311 — Write the six ADRs decided in D49 in docs/adr/ (0001 to 0006), each just before the first spec it affects. The content already exists in NOTEPAD.md; check the decision numbers cited in D49 as each is written.

## Phase 0: foundation

- [x] FEAT-20261010-1201 — Phase 0: create the repository layout with each framework's generator (backend/src structure, frontend with create-next-app, docs folders). Depends on ISS-20261010-1154. [2026-10-10 13:22]
- [ ] FEAT-20261010-1202 — Phase 0: build the Docker Compose stack: postgres 18, rabbitmq, valkey, seaweedfs, containers for api, worker, relay and maintenance, a one-shot migrate container, and an optional observability profile. Depends on FEAT-20261010-1201.
- [ ] FEAT-20261010-1203 — Phase 0: write the configuration module that stops at startup when a required setting is missing, plus a development .env.example with obviously fake values.
- [ ] FEAT-20261010-1204 — Phase 0: set up Alembic with its generator and write the first migration for all 11 tables in DATABASE.md, with the roles qfe_migrator and qfe_app.
- [ ] FEAT-20261010-1205 — Phase 0: observability skeleton: JSON logs with trace id, /metrics, /healthz and /readyz, and the collector configuration.
- [ ] FEAT-20261010-1206 — Phase 0: define the port interfaces (QueueAdapter, StorageAdapter, RateLimiter, Clock, IdGenerator), in-memory fakes and a shared contract test suite for each (spec: docs/specs/FEAT-20261010-1206-ports-and-contract-tests.md). AuthProvider moved to FEAT-20261010-1218 and the repository interfaces to FEAT-20261010-1211, approved 2026-10-10.
- [ ] FEAT-20261010-1207 — Phase 0: set up test scaffolding for unit, integration, contract and end-to-end levels, and the docs check that fails when a route has no file in docs/apis/.
- [o] FEAT-20261010-1208 — Phase 0: install the chosen dependency versions together in the project environment and run them, including httpx on Python 3.12 and Next.js with the TypeScript version its generator picks. Each dependency needs approval first (CLAUDE.md Module 5). Depends on ISS-20261010-1154 and ISS-20261010-1156.
- [ ] FEAT-20261010-1209 — Phase 0: SeaweedFS end-to-end checks from outside Docker: presigned POST with a size limit, the public URL setting, HEAD, and lifecycle expiry.
- [ ] FEAT-20261010-1319 — Phase 0: GitHub Actions workflow (D45) running ruff, mypy, the unit and contract tests, the docs check, the Compose-based integration tests and the frontend build. Side finding while writing the spec for FEAT-20261010-1207: ARCHITECTURE.md puts CI in Phase 0 but no item built it. Depends on FEAT-20261010-1207.

## Phase 1: core

- [ ] FEAT-20261010-1210 — Phase 1: domain layer: the job state machine as one transition table, and the retry delay function, with unit tests for every transition.
- [ ] FEAT-20261010-1211 — Phase 1: data-access: all repositories and transactional operations (accounts, files, jobs, outbox, maintenance) as described in docs/virtual-implementation/data-access.md, with integration tests. Uses FEAT-20261010-1210. Also defines the repository interfaces (moved here from FEAT-20261010-1206).
- [ ] FEAT-20261010-1212 — Phase 1: job type registry with the echo job type, the FileRef type, PermanentError and the handler contract.
- [ ] FEAT-20261010-1213 — Phase 1: queue adapter on RabbitMQ (one queue per job type, publish with confirms and returns, consume, ack, nack), with contract tests.
- [ ] FEAT-20261010-1214 — Phase 1: storage adapter on SeaweedFS (presigned upload, HEAD, download link, delete, read, write, ensure bucket), with contract tests.
- [ ] FEAT-20261010-1215 — Phase 1: outbox relay.
- [ ] FEAT-20261010-1216 — Phase 1: worker with pools through WORKER_JOB_TYPES, concurrency, heartbeat, graceful stop and the hard time cap. Depends on ISS-20261010-1155.
- [ ] FEAT-20261010-1217 — Phase 1: maintenance container: lease recovery, safety-net sweep, cleanups and job purge.
- [ ] FEAT-20261010-1218 — Phase 1: accounts and auth: signup (creates the first organisation), login, refresh with the reuse window, logout, API key create, list and revoke, and the credential checks. Also defines the AuthProvider interface (moved here from FEAT-20261010-1206).
- [ ] FEAT-20261010-1219 — Phase 1: rate limiter on Valkey with the four request classes and the fail-open and fail-closed rules, plus docs/rate-limits.md.
- [ ] FEAT-20261010-1220 — Phase 1: job API: submit, list, get, attempts and job types, each with its file in docs/apis/.
- [ ] FEAT-20261010-1221 — Phase 1: file API: upload link, get file, input file checks and the result file flow, each with its file in docs/apis/.
- [ ] FEAT-20261010-1222 — Phase 1: frontend foundation in Next.js (D50): route groups for the user area and a reserved, empty `(admin)` area, each with its own layout; the organisation as the first path segment without a label (`/<org_id>/...`); rules and helpers for URL-held state (filters, sort, page, tabs, modals); the auth shell and token refresh (D32); skeleton and transition patterns; design tokens and accessibility rules; and `docs/FRONTEND.md` with the conventions. Needs approval of each UI library first (Module 5). Depends on FEAT-20261010-1201.
- [ ] FEAT-20261010-1312 — Phase 1: frontend pages for signup, login and API keys (list, create with the key shown once, revoke), all URL-routable. Depends on FEAT-20261010-1222 and FEAT-20261010-1218.
- [ ] FEAT-20261010-1313 — Phase 1: frontend jobs pages: list with filters, sort and page held in the URL, job detail and attempts, with skeletons. Depends on FEAT-20261010-1222 and FEAT-20261010-1220. Submitting a job from the UI is the separate item FEAT-20261010-1318.
- [ ] FEAT-20261010-1317 — Phase 1: file API: list files for an organisation (paged, filter by status, newest first), with its file in docs/apis/, an index check in DATABASE.md and the organisation-isolation test. Not needed for Phase 0. Implement together with FEAT-20261010-1221 or right after it, before FEAT-20261010-1314.
- [ ] FEAT-20261010-1318 — Phase 1: frontend: submit a job from the UI (pick a job type, fill its input, attach uploaded files, show the new job). Not needed for Phase 0. Implement after FEAT-20261010-1313 (jobs pages), the job API FEAT-20261010-1220 and the file pages FEAT-20261010-1314, because the form reuses them.
- [ ] FEAT-20261010-1314 — Phase 1: frontend files pages: upload and file detail, with skeletons; the file list needs the list-files endpoint in FEAT-20261010-1317. Depends on FEAT-20261010-1222, FEAT-20261010-1221 and FEAT-20261010-1317.
- [ ] FEAT-20261010-1223 — Phase 1: observability dashboards and alerts.
- [ ] FEAT-20261010-1224 — Phase 1: one real sample handler that uses files and progress. Which one is still to be chosen.
- [ ] FEAT-20261010-1225 — Phase 1: end-to-end test flows for every full flow listed in ARCHITECTURE.md section 13.
- [ ] FEAT-20261010-1226 — Phase 1: organisation isolation contract test (one organisation can never read another's jobs or files through any repository method).
- [ ] FEAT-20261010-1227 — Phase 1: docs/apis/README.md, the short index of all endpoints.

## High findings to resolve

- [ ] ISS-20261010-1228 — Finding F-02: a relay row that cannot be published must leave the head of the queue (push its run_at out, alert on repeated failures). Resolve in the relay spec for FEAT-20261010-1215.
- [ ] ISS-20261010-1229 — Finding F-03: the relay holds a transaction and row locks while the broker is down. Resolve in the relay spec for FEAT-20261010-1215.
- [ ] ISS-20261010-1230 — Findings F-04 and F-38: decide and build how handlers run so heartbeats never stop and a hung handler is stopped. Resolve in the worker spec for FEAT-20261010-1216.
- [ ] ISS-20261010-1231 — Finding F-05: a planned worker stop must not consume an attempt (release-lease operation). Resolve in the worker and data-access specs.
- [ ] ISS-20261010-1232 — Finding F-06: limit requests that carry bogus credentials. The proxy-related part is deferred by D43.
- [ ] ISS-20261010-1233 — Finding F-08: define the result file flow and limit handler storage access to the organisation's key prefix. Resolve in the file API and worker specs.
- [ ] ISS-20261010-1234 — Resolve the other findings (F-01 and F-09 to F-40, except those above) inside the spec of the part each one belongs to. The list is in docs/virtual-implementation/findings.md section 2.

## Phase 2

- [ ] FEAT-20261010-1235 — Phase 2: priorities (RabbitMQ priority on each per-type queue).
- [ ] FEAT-20261010-1236 — Phase 2: delayed and scheduled jobs.
- [ ] FEAT-20261010-1237 — Phase 2: cancel a job.
- [ ] FEAT-20261010-1238 — Phase 2: completion webhooks, with webhook_endpoints and webhook_deliveries tables.
- [ ] FEAT-20261010-1239 — Phase 2: manual retry of a failed job (a retry endpoint on one job); it reopens a final state, so it needs its own spec.

## Deferred (not Phase 1)

- [ ] WISH-20261010-1240 — Deferred: email verification and the email sender (EmailSender port, SMTP adapter, mail-catcher container, resend limit, rules for unverified users).
- [ ] WISH-20261010-1241 — Deferred: password reset (needs the email sender).
- [ ] WISH-20261010-1242 — Deferred: member invitations (need the email sender).
- [ ] WISH-20261010-1243 — Deferred: account recovery for a forgotten password in Phase 1.
- [ ] WISH-20261010-1244 — Deferred: idle session timeout, an active sessions view and per-device logout.
- [ ] WISH-20261010-1245 — Deferred: password re-entry before creating or revoking an API key.
- [ ] WISH-20261010-1246 — Deferred: access-token denylist, to revoke tokens before they expire.
- [ ] WISH-20261010-1247 — Deferred: token-based CSRF protection (Phase 1 has SameSite cookies plus an origin check).
- [ ] WISH-20261010-1248 — Deferred: OAuth login providers (Google, GitHub) through the AuthProvider port.
- [ ] WISH-20261010-1249 — Deferred: asymmetric JWT signing and a key id.
- [ ] WISH-20261010-1250 — Deferred: trusted-proxy setting for client IP addresses, and a per-email login limit.
- [ ] WISH-20261010-1251 — Deferred: fail a job after N failed publishes of its outbox row.
- [ ] WISH-20261010-1252 — Deferred: maximum wait for a job type that has no workers.
- [ ] WISH-20261010-1253 — Deferred: LISTEN/NOTIFY wake-up for the relay (needs a direct database connection).
- [ ] WISH-20261010-1254 — Deferred: handler version against jobs.type_version mismatch.
- [ ] WISH-20261010-1255 — Deferred: lock-free, overshoot-tolerant job submit, only if per-organisation lock contention becomes a problem.
- [ ] WISH-20261010-1256 — Deferred: per-organisation limit overrides.
- [ ] WISH-20261010-1257 — Deferred: other queue adapters (Postgres queue, Redis Streams, SQS).
- [ ] WISH-20261010-1258 — Deferred: external (third-party) workers.
- [ ] WISH-20261010-1259 — Deferred: live progress streaming (SSE).
- [ ] WISH-20261010-1300 — Deferred: fair scheduling between organisations inside one job type's queue.
- [ ] WISH-20261010-1301 — Deferred: multipart upload for very large files.
- [ ] WISH-20261010-1302 — Deferred: virus or content scanning of uploads.
- [ ] WISH-20261010-1303 — Deferred: time partitioning of the jobs table (partition by id range; move idempotency into its own table).
- [ ] WISH-20261010-1304 — Deferred: organisation and user deletion flow, and erasing personal data.
- [ ] WISH-20261010-1305 — Deferred: audit log of user and key actions (hard to add later without gaps, so decide early).
- [ ] WISH-20261010-1306 — Deferred: billing and usage metering.
- [ ] WISH-20261010-1307 — Deferred: PostgreSQL row-level security as a second isolation layer.
- [ ] WISH-20261010-1308 — Deferred: tested down-migrations.
- [ ] WISH-20261010-1309 — Deferred by D43: production deployment: ingress and TLS (finding F-07), backups, secret management, published ports, CI for deployment.
- [ ] WISH-20261010-1310 — Deferred: PgBouncer, and the advisory lock test under PgBouncer transaction pooling.
- [ ] WISH-20261010-1315 — Deferred (D50): admin / platform-admin area: a platform-admin role in the data model, admin APIs (organisations, users, jobs and queues across organisations, each documented in docs/apis/) and the admin pages in the reserved `(admin)` route group. Needs its own design first; ties to the roles and scopes question in ISS-20261010-1155.
- [ ] WISH-20261010-1316 — Deferred (D50): the backend-for-frontend pattern (Next.js holds the session cookie and calls the API) if server-rendered data becomes important. It would rework D32.
