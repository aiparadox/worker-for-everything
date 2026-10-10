# Findings

Phase 5. Written from the 14 part files and the overview, which were written from `ARCHITECTURE.md`, `DATABASE.md` and `NOTEPAD.md` (all read-only and untouched). Tags are explained in [overview.md](overview.md) section 0. Nothing here has been applied to the sources.

How to read it:
- **Section 2** lists real problems: things wrong or missing in the documented design whatever the load is.
- **Section 3** lists risks that only bite if a condition is true. They are kept apart on purpose.
- **Sections 5 and 6** register every `ASSUMPTION` and `CONFLICT` tag used in the folder.

---

## 1. Verification pass (Phase 4)

| Check | Method | Result |
|---|---|---|
| Every `ARCH`, `DB` and `NOTEPAD` tag points at a real heading, table, column or decision | Script run over all 15 files | 0 unresolved. The four hits were the placeholder examples in the legend of `overview.md` |
| Every cross-part interface reference (the `part#interface` tags) is defined in the owner's section 2 | Script | 70 distinct references, 0 unresolved |
| Interface names in the overview exist in the owner file | Script | 0 missing after the overview was brought in line with the part files (22 connection rows became 29; the catalogue was rewritten) |
| Columns in `DATABASE.md` that no part mentions | Script | Only audit timestamps (`created_at`, `updated_at`), `users.email_verified_at` (deliberately empty) and `jobs.cancel_requested` (Phase 2). One real gap: nothing says what maintains `jobs.updated_at` (F-35) |
| Every part named in `ARCHITECTURE.md` has a file | Manual | Containers and adapters all map to a part. Gaps: `domain/` has no owner (F-22) and `handlers/` is folded into `worker` [ARCH: 6. Code structure and the adapter rule] |
| Producer output matches consumer input at each connection | Manual, row by row | Matches, except: the delivery object lacks the routing key the worker relies on (F-21); `max_attempts` has two authorities (F-12); the worker never names the `gate` that the queue adapter asks for (F-21) |
| No deferred item silently assumed decided | Manual, 31 distinct `DEFERRED` tags | None found. Each part states the Phase 1 behaviour next to the deferral |
| Failure, concurrency and authorisation at every hop | Manual | Covered in sections 6, 7 and 9 of each file. Weak hops: client to storage (F-10), unauthenticated requests (F-06), broker credentials (QA-12) |

Tag counts across the 15 files: 172 distinct assumption IDs, 5 real conflict IDs, and 31 distinct deferred items referenced.

### Coverage of the behaviour tests in `ARCHITECTURE.md` section 13

Every test the architecture asks for has a part that must make it pass and a failure-mode row that describes it. [ARCH: 13. Testing]

| Test | Parts | Where the failure mode is written |
|---|---|---|
| Duplicate message runs a job once; early message refused | `worker`, `data-access` | `data-access.md` §6, `worker.md` §6 |
| Crash before and after the claim | `worker`, `data-access`, `queue-adapter` | `worker.md` §6 |
| Job that kills every worker fails after `max_attempts` | `maintenance`, `data-access` | `maintenance.md` §5.1 |
| Stale worker's finish is rejected | `data-access` | `data-access.md` §6 |
| Publish to a type with no queue is a failed publish | `queue-adapter`, `outbox-relay` | `queue-adapter.md` §6 |
| Messages wait when nobody listens | `queue-adapter`, `platform` | `job-type-registry.md` §6, `platform.md` §5.3 |
| At most one unclaimed message per queue; pools isolate slow jobs | `worker`, `queue-adapter` | `worker.md` §7 (rests on QA-03 and QA-05) |
| Sweep grows its wait and does not flood | `maintenance`, `data-access` | `maintenance.md` §5.2 |
| Same idempotency key at once gives one job; cap never exceeded | `data-access`, `job-api` | `data-access.md` §7 |
| Another organisation's file is rejected | `file-api`, `data-access` | `file-api.md` §6 |
| Slow storage does not lengthen the lock | `job-api`, `file-api` | `file-api.md` §8 |
| Two tabs refresh the same token | `accounts-auth`, `data-access`, `frontend` | `accounts-auth.md` §7 |
| Outbox cleanup does not reset the sweep wait | `maintenance`, `data-access` | `maintenance.md` §5.3 |
| Redis down: refresh works, login rejected | `rate-limiter`, `accounts-auth` | `rate-limiter.md` §6 |
| Organisation isolation contract test | `data-access` | `data-access.md` §9 |

---

## 2. Real problems (sorted by severity)

Severity: **High** = likely to cause an incident or break a guarantee in normal use. **Medium** = a real gap or defect that will cost time or cause bugs. **Low** = untidy or minor.

| # | Severity | Category | Where | Problem | Suggested fix | Blocks which deferred item |
|---|---|---|---|---|---|---|
| F-01 | High | Correctness | `job-api.md` §5.1; `ARCHITECTURE.md` §5, §7, §11 | A repeated submit is not safe. File checks (storage calls) run before the transaction, and the idempotency lookup runs inside it, so a repeat redoes the storage work and can fail on a purged or changed file instead of returning the existing job, which §7 promises. [ARCH: 5. Life of a job] [ARCH: 7. Data model] [ARCH: 11. Reliability and delivery] [CONFLICT C-02] | Look up `(organisation_id, idempotency_key)` first, read-only and before any file work, and return the existing job. Keep the locked re-check inside the transaction for races | None |
| F-02 | High | Availability | `outbox-relay.md` §6; `DATABASE.md` §4.11 | A row that cannot be published stays due. The relay orders by `run_at, id` and re-selects it every cycle with no backoff, so enough such rows fill the batch and publishing stops for everyone. [DB: outbox.run_at; §4.11] [ARCH: 11. Reliability and delivery] [ASSUMPTION RLY-03] | On a failed publish push the row out (`run_at = now() + backoff`, capped) so it leaves the head. Alert on `publish_attempts` above a threshold | Failing a job after N failed publishes |
| F-03 | High | Availability | `outbox-relay.md` §6, §8 | The batch transaction and its row locks stay open while the relay waits on the broker. With the broker down, one batch can hold them for batch size times the publish timeout (100 rows and a 10 second timeout, my numbers, is about 17 minutes). [DB: outbox; §4.11 rules] [ASSUMPTION RLY-04] [ASSUMPTION RLY-05] | Stop the cycle after the first few failures. Or claim rows with a short lease update, commit, publish outside the transaction, then mark | None |
| F-04 | High | Correctness | `worker.md` §6; `ARCHITECTURE.md` §10, §11 | Heartbeats cannot run if a handler blocks the event loop, which OCR code does. The lease expires, recovery requeues a job that is still running, and it runs twice. The sources do not say where handlers run, how a timeout is enforced, or how a running handler is stopped. [ARCH: 11. Reliability and delivery] [ASSUMPTION A-13] [ASSUMPTION WK-02] [ASSUMPTION WK-08] | Run handlers in a thread or child process, heartbeat from the event loop, and kill the handler on timeout or lease loss | None |
| F-05 | High | Correctness | `worker.md` §6; `DATABASE.md` §5 | A worker stopped on purpose (deploy, scale-in) leaves its lease to expire. The attempt was counted at claim, so every deploy burns one attempt, and with `max_attempts` of 4 a few deploys fail healthy jobs. [DB: jobs.attempts; §5 Worker claim] [DB: jobs.lease_expires_at; §5 Recover] [ASSUMPTION WK-05] | Graceful shutdown: finish the job, or release the lease with a new operation that sets `retrying` without consuming an attempt. Do not count `lease_lost` attempts against `max_attempts` | None |
| F-06 | High | Security | `rate-limiter.md` §6; `accounts-auth.md` §8 | Requests with bogus credentials are never limited. Key limits need a valid key, and the IP limits cover only login, signup, refresh and logout, yet each bogus API call costs a database read. [ARCH: 9. Rate limiting] [ASSUMPTION RL-06] [ASSUMPTION AA-14] [ASSUMPTION DA-18] | Add an IP-based limit on unauthenticated and failing requests, before the lookup, and a short negative cache for unknown prefixes | Trusted-proxy setting and per-email login limit |
| F-07 | High | Deployment | `platform.md` §2.1, §9; `ARCHITECTURE.md` §4, §8, §9 | No ingress, reverse proxy or TLS terminator is in the topology, yet the `Secure` cookie, the same-site rule, per-IP limits and the public presigned storage URL all assume one. [ARCH: Containers (Docker Compose)] [ARCH: 8. Authentication and authorisation] [ARCH: 9. Rate limiting] [ASSUMPTION PLT-05] | Add an ingress to the topology and decide its trusted-proxy handling in Phase 1, or label Phase 1 development-only | Trusted-proxy setting and per-email login limit |
| F-08 | Medium | Missing flow | `file-api.md` §1, `worker.md` §5.4; `ARCHITECTURE.md` §17 | Result files have no flow. Nothing says who creates a `files` row of kind `result`, how the object is written, or how the link is found, yet Phase 1 ships a sample handler that uses files. [DB: files.kind] [ARCH: 17. Roadmap] [ASSUMPTION A-11] [ASSUMPTION WK-03] | Define one interface that registers a result file (row plus object) and have the worker call it; say who decides inline versus file | None |
| F-09 | Medium | Data lifecycle | `maintenance.md` §1, §5.4; `DATABASE.md` §10 | Nothing deletes files that jobs used or files marked `available` that no job ever used. The rule "removed with the last job that uses them" has no mechanism, the job and link rows cascade away, and the lifecycle rule removes objects but not rows. [DB: 10. Retention and cleanup; files] [DB: job_files] [CONFLICT C-05] [ASSUMPTION FA-10] [ASSUMPTION DA-07] | Add a files cleanup chore ordered by foreign keys: files unreferenced for a period, then their objects. Say whether `expires_at` is cleared on `available` | Organisation and user deletion flow |
| F-10 | Medium | Security | `storage-adapter.md` §7; `file-api.md` §7 | An upload link stays valid after the file is checked, so the bytes can change between the check and the worker's read. [NOTEPAD: D36] [ASSUMPTION SA-05] | Keep link lifetimes short, record the object's ETag at the check and compare it in the worker, or copy the object to a validated key | None |
| F-11 | Medium | Delivery | `queue-adapter.md` §2.1, §2.3, §5.3 | The guarantees rest on settings the sources never state: persistent messages (without them a broker restart empties durable queues), a prefetch of 1 (without it "at most one unclaimed message per queue" is false), and the order cancel-before-ack (without it each busy worker holds a prefetched message for the whole job). [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-02] [ASSUMPTION QA-03] [ASSUMPTION QA-05] | State all three in section 11. Add them to the `QueueAdapter` contract suite | None |
| F-12 | Medium | Consistency | `job-type-registry.md` §4, `worker.md` §5.4 | `max_attempts` has two authorities: the copy on the job and the value in the definition. The worker decides with the job's value, then asks `next-retry-delay`, which may use the definition's value and answer `no-more-retries` (or the reverse). [DB: jobs.max_attempts] [ARCH: 10. Job types and handlers (how new work plugs in)] [ASSUMPTION JTR-05] | Make `next-retry-delay` take `max_attempts` and `retry_delays` from the job (snapshot both at submit), or return only a delay | None |
| F-13 | Medium | Enforcement gap | `data-access.md` §2.1; `accounts-auth.md` §2.7 | `organisations.status = suspended` is said to "block an organisation's API access", but no interface sets it and the key check does not read it. `users.status` has the same gap. [DB: organisations.status] [DB: users.status] [ASSUMPTION DA-05] [ASSUMPTION AA-12] | Have `find-api-key-by-prefix` return organisation and creator status, reject suspended or disabled, and say who sets them | None |
| F-14 | Medium | Authorisation | `accounts-auth.md` §2.5; `job-api.md` §2 | Roles (`owner`, `admin`, `member`) have no listed permissions, and the sources give the scope of only one endpoint (`GET /v1/files/{id}` needs `files:read`). Which credential kind `GET /v1/job-types` accepts is unknown. [DB: memberships.role] [ARCH: 14. API documentation rules] [ASSUMPTION AA-05] [ASSUMPTION A-14] | Add a table: endpoint, credential kind, scope, minimum role | None |
| F-15 | Medium | Performance | `file-api.md` §5.2, §8 | Checking input files does one database read per file and one storage HEAD per file in turn, even for files already `available`, and nothing caps the number of `FileRef` values in a payload, so a payload can force thousands of storage calls before the transaction. [ARCH: 5. Life of a job] [DB: 8. Write load and size limits] [ASSUMPTION FA-05] [ASSUMPTION FA-12] [ASSUMPTION SA-07] | Cap files per payload, fetch rows in one query, run HEADs in parallel with a timeout, skip HEAD for `available` files that are young | None |
| F-16 | Medium | Performance | `data-access.md` §8; `accounts-auth.md` §8 | Every API-key request reads the key row, and the throttled `last_used_at` write may still be one statement per request. No cache is described. [DB: api_keys.key_prefix] [DB: api_keys.last_used_at] [ASSUMPTION DA-06] [ASSUMPTION DA-18] | Cache verified keys for a short time (revocation takes effect after it), and keep the last-used throttle in memory or write it asynchronously | None |
| F-17 | Medium | Availability | `observability.md` §2.4, §6 | If `/readyz` includes Redis or RabbitMQ, an outage makes the API look unready although submits do not need the broker and the Redis limits fail open by design. [ARCH: 12. Observability] [ARCH: 9. Rate limiting] [ASSUMPTION OBS-06] | Define readiness per process; leave out optional dependencies | None |
| F-18 | Medium | Availability | `platform.md` §5.1, §6 | Every process that knows a type declares its queue at startup. If that is fatal, the API cannot restart while RabbitMQ is down, which defeats the outbox's purpose. [ARCH: 11. Reliability and delivery] [ASSUMPTION PLT-04] | Make declaration non-fatal for the API with background retry; fatal for relay and worker | None |
| F-19 | Medium | Performance | `maintenance.md` §5.3; `DATABASE.md` §4.11, §10 | Published outbox rows are deleted by age, but the only outbox indexes are for unpublished rows and `job_id`. The cleanup has no stated access path and may scan the table. [DB: outbox.published_at] [DB: 10. Retention and cleanup; outbox] | Delete by `id` range (ids are time-ordered) with `published_at IS NOT NULL`, or add `(id) WHERE published_at IS NOT NULL` | None |
| F-20 | Medium | Data lifecycle | `maintenance.md` §5.4, §8; `data-access.md` §2.6 | The purge cuts by `id` range, which measures time from creation, while the intent is "keep for N days". A job that finishes after long retries is deleted early or kept long, and there is no metric or alert for purge falling behind ingest. [DB: 10. Retention and cleanup; jobs] [ASSUMPTION MT-04] [ASSUMPTION MT-05] | Decide the basis (creation or `finished_at`), index it if needed, and alert on the age of the oldest purgeable row | Time partitioning of jobs |
| F-21 | Medium | Interface mismatch | `queue-adapter.md` §2.3; `worker.md` §5.2 | The worker finds the job type from the delivery's routing key before it claims, but the queue adapter's delivery object lists only body, headers and ack handles. The worker also never defines the `gate` signal the adapter needs. [ARCH: Worker pools and concurrency (D35)] [ASSUMPTION QA-08] [ASSUMPTION WK-01] | Add the routing key to the delivery object and define the gate in the worker | None |
| F-22 | Medium | Structure | `ARCHITECTURE.md` §6; `data-access.md` §2.3, §2.4 | `domain/` is meant to hold state transitions, but no part owns them. The state machine is encoded as SQL conditions in five separate operations, so drift between them is possible and there is nothing to unit test. [ARCH: 6. Code structure and the adapter rule] [ARCH: State machine] | Put the transition table in `domain/` and test each data-access operation against it | None |
| F-23 | Medium | Config | `platform.md` §2.2; `ARCHITECTURE.md` §15 | The tuning list is incomplete. Parts need relay poll interval, batch size and publish timeout, maintenance intervals and batch sizes, the API-key last-used interval, the progress write interval, storage HEAD and Redis timeouts, none of which are listed. [ARCH: 15. Configuration] [ASSUMPTION RLY-05] [ASSUMPTION MT-01] [ASSUMPTION RL-05] | Extend the list and say where defaults are documented | None |
| F-24 | Medium | Security | `accounts-auth.md` §8, §9 | Argon2 login and signup are CPU-heavy and may run on the event loop, the per-IP limit does not work behind a proxy, and signup reveals whether an email exists. [ARCH: 8. Authentication and authorisation] [ARCH: 9. Rate limiting] [ASSUMPTION AA-04] [ASSUMPTION AA-13] | Hash in a worker thread, add a per-email limit, return the same answer for unknown email and wrong password | Trusted-proxy setting and per-email login limit |
| F-25 | Medium | Security | `accounts-auth.md` §2.10, §9; `frontend.md` §9 | The origin check has no owner or allowed-origin list, and the access token in page memory can be read by injected script with no content-security policy described. [ARCH: 16. Security notes] [ASSUMPTION AA-07] [ASSUMPTION AA-15] [ASSUMPTION FE-05] | Assign the check to middleware with a configured allowlist; specify a content-security policy | Token-based CSRF protection |
| F-26 | Medium | Security | `job-api.md` §9 | `jobs.error` carries `message` text from handlers and libraries and is returned to clients. It may leak internals or other tenants' data. [DB: jobs.error] [ASSUMPTION JA-10] | Return an error code and a filtered message; keep full text in logs | None |
| F-27 | Medium | Abuse | `file-api.md` §8; `rate-limiter.md` §1 | No limit on storage per organisation or on files per organisation: rate limits count requests, not bytes, and `available` files persist. [ARCH: 9. Rate limiting] [ASSUMPTION FA-09] [ASSUMPTION RL-11] | Add a per-organisation storage and file-count quota | Billing and usage metering |
| F-28 | Medium | Contract | `file-api.md` §2.1; `storage-adapter.md` §2 | The upload link shape is unsettled: the decision names a "presigned upload URL", the verification result says to use a presigned POST policy (URL plus form fields) so a size range is enforced. [NOTEPAD: D31] [NOTEPAD: Phase 0 verification results] [CONFLICT C-04] | Decide on the POST policy and write the response shape | None |
| F-29 | Medium | Contract | `job-api.md` §5.1 | `request_hash` is computed from "type and payload" without a canonical form, so key order or whitespace can turn a true repeat into a false conflict. [DB: jobs.request_hash] [ASSUMPTION JA-02] | Hash a canonical JSON serialisation | None |
| F-30 | Medium | Documentation | `NOTEPAD.md` D3, D7, D9, D10, D15, D16, D17, D27 | Stale entries contradict later decisions and carry no supersession note: D15's state machine sends `retrying` back to `queued`; D10 still lists a dead-letter queue and `run_at` as unused; D3, D7 and D9 describe a browser session cookie; D16 and D17 route the active-jobs count through the rate limiter; D27 names outbox-based counting. A new session reading them would build the old design. [NOTEPAD: D15] [NOTEPAD: D10] [NOTEPAD: D7] [NOTEPAD: D16] [NOTEPAD: D17] [NOTEPAD: D27] [CONFLICT C-03] | Add supersession notes (snippet in section 7) | None |
| F-31 | Medium | Operations | `platform.md` §4, §9, §10 | Backups and restore, secret delivery and rotation, published ports, and the CI tool are not described anywhere. [ARCH: 15. Configuration] [ASSUMPTION PLT-02] [ASSUMPTION PLT-06] [ASSUMPTION PLT-09] [ASSUMPTION PLT-10] | Decide them in Phase 0 and record them | None |
| F-32 | Medium | Security | `accounts-auth.md` §9; `platform.md` §6 | The JWT algorithm, secret rotation and clock-skew leeway are unstated; a rotated secret invalidates every token. [ARCH: 8. Authentication and authorisation] [ASSUMPTION AA-06] [ASSUMPTION PLT-07] | Choose the algorithm, allow two valid secrets during rotation, set a small leeway | Asymmetric JWT signing and a key id |
| F-33 | Low | Contract | `rate-limiter.md` §2.2; `ARCHITECTURE.md` §3, §9, §17; `DATABASE.md` §6, §7 | The number of Redis limits is stated as three, four, and "all four" in different places, while the table lists four Redis classes plus the Postgres cap. [ARCH: 9. Rate limiting] [ARCH: 17. Roadmap] [DB: 6. The active-jobs cap (D29)] [NOTEPAD: D17] [CONFLICT C-01] | State "four Redis classes and one Postgres cap" everywhere | None |
| F-34 | Low | Data | `data-access.md` §2 | Nothing says how `jobs.updated_at` and other `updated_at` columns are maintained (trigger or every statement). [DB: jobs.updated_at] [DB: 2. Conventions] | State a trigger or a rule that every update sets it | None |
| F-35 | Low | Observability | `observability.md` §8 | No sampling or log-level policy, and `jobs_failed_total` has no bounded error-code list. [ARCH: 12. Observability] [ASSUMPTION OBS-03] [ASSUMPTION OBS-04] | Define a small set of error codes and a sampling rule | None |
| F-36 | Low | Idempotency | `job-api.md` §7 | Without an idempotency key, a lost response means the client cannot know whether a job exists, and a retry creates a second one. [DB: jobs.idempotency_key] [ASSUMPTION JA-08] | Document it; encourage keys; consider requiring one for costly job types | None |
| F-37 | Low | Terminology | `NOTEPAD.md` section 6.1, D23 | The "short wait" before a delivered message is handed back and the "gate" are described in prose in two places but never given a name or a default. [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-09] | Name both as settings in section 15 | None |

---

## 3. Risks that depend on a condition

These are not defects in the design. They become problems if the stated condition is true. The load numbers are my assumptions from section 8 of the overview. [ASSUMPTION L-01]

| # | If this is true | Then this breaks | Where | Mitigation to consider |
|---|---|---|---|---|
| K-01 | Heavy pools run at concurrency 1 and 2,000 jobs run at once | 2,000 worker processes each hold a Postgres and a RabbitMQ connection, while PgBouncer "is not needed in the first version". Postgres connection limits are the first thing to break. [ARCH: Worker pools and concurrency (D35)] [NOTEPAD: Phase 0 verification results] [ASSUMPTION L-02] [ASSUMPTION WK-10] [ASSUMPTION QA-10] | `worker.md` §8; `queue-adapter.md` §8 | Add PgBouncer in the first version, or share one connection across jobs in a process, or fewer larger processes |
| K-02 | An organisation fills a slow type's queue up to its cap (low thousands) | Every other organisation waits behind it, because a type's queue is first-in-first-out across organisations. [ARCH: 11. Reliability and delivery] [DEFERRED: fair scheduling between organisations inside one job type's queue] | `queue-adapter.md` §7 | Lower caps for slow types, or per-type caps |
| K-03 | Clients poll each job every 2 seconds at 2,000 running jobs | About 1,000 reads per second, each with a key lookup and two Redis counters. No push exists. [NOTEPAD: D11] [ASSUMPTION JA-09] | `job-api.md` §8 | Cache key lookups, return `ETag` or `Retry-After`, bring webhooks forward |
| K-04 | 30 days of retention at 50 submits per second | About 130 million `jobs` rows plus attempts and outbox rows; purge and vacuum must keep up and partitioning is deferred. [DB: 11. Growth plan] [ASSUMPTION L-05] | `data-access.md` §8; `maintenance.md` §8 | Shorter retention, or pull partitioning forward |
| K-05 | Redis is slow but not down | Every API request waits on counters and no timeout is described. [ARCH: 9. Rate limiting] [ASSUMPTION RL-05] | `rate-limiter.md` §6 | Short timeout and a circuit breaker that triggers the fail-open path |
| K-06 | Storage HEAD takes 200 ms and a payload has 3 files | 0.6 seconds of storage time per submit before the transaction; more with more files. [NOTEPAD: D36] [ASSUMPTION SA-07] | `file-api.md` §8 | Parallel HEADs, cap files per payload (F-15) |
| K-07 | A job type is removed while jobs of that type wait or run | Their queue is orphaned, and recovery cannot compute a retry delay without the definition. [NOTEPAD: D28] [ASSUMPTION MT-02] | `maintenance.md` §5.1 | Keep definitions for a deprecation period, or fail such jobs explicitly |
| K-08 | Logs and traces are not sampled | Loki and Tempo ingest grows with polling traffic. [ARCH: 12. Observability] [ASSUMPTION OBS-03] | `observability.md` §8 | Sampling policy |
| K-09 | The broker restarts with non-persistent messages | All queued messages vanish and every waiting job needs a sweep, the first after 5 minutes. [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-02] | `queue-adapter.md` §6 | Persistent messages (F-11) |
| K-10 | A later release adds RabbitMQ priorities | Queue priority arguments are fixed at declaration, so the idempotent declare at startup would be refused on existing queues. [DEFERRED: priorities on the per-type queues] [ASSUMPTION QA-06] | `queue-adapter.md` §10 | Plan a queue migration or new queue names |
| K-11 | Someone needs to delete an organisation before the deletion flow exists | `ON DELETE RESTRICT` blocks it. [DB: jobs.organisation_id] [DEFERRED: organisation and user deletion flow] | `data-access.md` §10 | Decide the interim procedure |
| K-12 | Many sweeps for a type nobody consumes | Duplicates accumulate in that queue, bounded by the growing wait. [DB: jobs.sweep_count; §5 Sweep] [DEFERRED: maximum wait for a type with no workers] | `maintenance.md` §6 | Alert only; already described |

Risks the documents already accept by decision, listed so nobody rediscovers them as bugs: no account recovery and open signup in Phase 1, per-IP limits behind a proxy, Redis outage opening request limits, the access token surviving logout for about 15 minutes, a thief inside the reuse window being rejected but not punished. [ARCH: 19. Known risks] [NOTEPAD: D37] [DEFERRED: account recovery]

---

## 4. Conflicts register

| ID | Sources that disagree | Quote or summary | Raised in |
|---|---|---|---|
| C-01 | `ARCHITECTURE.md` §9 and §17, `DATABASE.md` §6 and §7, `NOTEPAD.md` D17 and D29 | §9 says "Three request-rate limits live in Redis" but its table has four Redis rows; §17 says "all four limits"; DB §6 says Redis keeps "only the three"; D17 says "four limits". [ARCH: 9. Rate limiting] [ARCH: 17. Roadmap] [DB: 6. The active-jobs cap (D29)] [NOTEPAD: D17] | `rate-limiter.md` §2.2 |
| C-02 | `ARCHITECTURE.md` §5 against §7 and §11 | §5 puts file checks before the transaction; §7 says a retried submit "gets the same job back"; §11 says the key is checked "under the organisation lock". [ARCH: 5. Life of a job] [ARCH: 7. Data model] [ARCH: 11. Reliability and delivery] | `overview.md` F4, `job-api.md`, `file-api.md` |
| C-03 | `NOTEPAD.md` D3, D7, D9, D10, D15, D16, D17, D27 against D22 to D40 | Stale text with no supersession note; see F-30. [NOTEPAD: D15] [NOTEPAD: D10] [NOTEPAD: D7] [NOTEPAD: D16] [NOTEPAD: D27] | This file only |
| C-04 | `NOTEPAD.md` D31 against "Phase 0 verification results", and `DATABASE.md` §4.7 | D31 says "presigned upload URL"; requirement 7 says to use a presigned POST policy; DB §4.7 says the real size "must match the declared limit" without saying declared size or the cap. [NOTEPAD: D31] [NOTEPAD: Phase 0 verification results] [DB: files.size_bytes] | `overview.md` F4, `storage-adapter.md`, `file-api.md` |
| C-05 | `DATABASE.md` §10 against §4.7, §4.8, §4.9 | §10 says used files are "removed with the last job that uses them, via `job_files`", but `job_files` rows cascade away with the job and the foreign keys keep the file rows, so no step deletes them. [DB: 10. Retention and cleanup; files] [DB: job_files] [DB: jobs.result_file_id] | `data-access.md`, `maintenance.md`, `file-api.md`, `overview.md` |

The tag `[CONFLICT DA-C1]` in the legend of `overview.md` is only an example of the syntax.

---

## 5. Assumption register

Every `ASSUMPTION` ID used in the folder, one line each. Where the sources are silent I inferred; none of these is a stated fact. IDs not listed were never used.

### Overview (A-nn) and load (L-nn)

| ID | What was assumed |
|---|---|
| A-01 | Interface names and ID prefixes are labels I chose |
| A-02 | Paths and wire format of the auth endpoints (the sources list only logical names; error bodies are JSON) |
| A-04 | Signup writes user, identity, organisation and membership in one transaction; how the organisation `slug` is chosen |
| A-05 | How logout identifies the token family |
| A-06 | A page reload needs a refresh because the access token is only in memory |
| A-07 | How the API tells a browser token from an API key (both `Authorization: Bearer`) |
| A-08 | Order of credential check and rate limit; which limit covers key-management endpoints |
| A-09 | `202` on submit; status code of an idempotent repeat |
| A-10 | Status and `Retry-After` when the active-jobs cap is hit |
| A-11 | Who writes `files` rows of kind `result` |
| A-12 | Which processes expose `/metrics` and the health endpoints, and who can reach them |
| A-13 | Whether handlers run on the event loop, a thread or a process |
| A-14 | Scope and credential kind required per endpoint |
| L-01 to L-07 | Load: 50 submits per second (200 peak), 2,000 running jobs, 60 s lease and 20 s heartbeat, 1,000 organisations and 5,000 users, 30-day retention, 1 s relay polling with batches of 100, 10 types in 4 pools |

### data-access

| ID | What was assumed |
|---|---|
| DA-01 | Typed outcome names (the sources define none) |
| DA-02 | How an organisation `slug` is derived |
| DA-03 | The four signup inserts are atomic |
| DA-04 | On a key prefix collision the caller retries |
| DA-05 | Whether the key lookup also returns organisation status |
| DA-06 | Where the `last_used_at` throttle lives (SQL or memory) |
| DA-07 | Whether `files.expires_at` is cleared when a file becomes `available` |
| DA-08 | List filters beyond `status`, and page size bounds |
| DA-09 | `list-attempts` isolates by joining to `jobs` |
| DA-10 | A claim refusal reason needs a follow-up read |
| DA-11 | Recovery takes a caller-supplied `delay_for` |
| DA-12 | Pending-file cleanup returns keys and the caller deletes objects, not atomically |
| DA-13 | Initial values on job insert |
| DA-14 | Row lock when rotating a refresh token |
| DA-15 | Failure counts are lost if the batch transaction rolls back |
| DA-16 | Lock ordering across other transactions is unspecified |
| DA-17 | Revoke and mark operations are safe to repeat |
| DA-18 | No key cache; one database read per API request |
| DA-19 | `list-api-key-rows` has no limit |

### job-type-registry

| ID | What was assumed |
|---|---|
| JTR-01 | Shape and status of payload validation errors |
| JTR-02 | Behaviour when fewer delays than retries are configured |
| JTR-03 | Source and distribution of jitter (no random source among the ports) |
| JTR-04 | Duplicate or malformed registrations stop startup; the registry is immutable |
| JTR-05 | Retry delays and jitter are not snapshotted on the job |
| JTR-06 | Wire form of `FileRef`, and whether nested or optional ones are allowed |
| JTR-07 | Who validates results against `output_schema`; whether `handle` is async |
| JTR-08 | Who enforces `timeout` |
| JTR-09 | Content and caching of the job-types response |
| JTR-10 | Payload validation is CPU-bound in the API process |

### queue-adapter

| ID | What was assumed |
|---|---|
| QA-01 | Exchange name and queue arguments |
| QA-02 | Message persistence |
| QA-03 | Prefetch value |
| QA-04 | Reconnect and consumer resume behaviour |
| QA-05 | Cancel-before-ack sequence at concurrency 1, and the churn it causes |
| QA-06 | Queue priority arguments are fixed at declaration |
| QA-07 | Publish concurrency and throughput |
| QA-08 | Fields of the delivery object |
| QA-09 | Publish timeout and the hand-back wait |
| QA-10 | Thousands of connections at the assumed load |
| QA-11 | The adapter passes trace headers through unchanged |
| QA-12 | Separate broker users and permissions are not described |

### storage-adapter

| ID | What was assumed |
|---|---|
| SA-01 | Separate public and internal storage addresses |
| SA-02 | `read-object` and `write-object` exist for handlers |
| SA-03 | Who maps a file id to a storage key for handlers |
| SA-04 | Who creates the bucket and its lifecycle rule |
| SA-05 | An upload link stays usable after validation |
| SA-06 | Key and content type are pinned in the upload policy |
| SA-07 | Parallelism and timeouts of HEAD calls; idempotent handler writes |
| SA-08 | Orphan objects when a delete fails after the row is deleted |
| SA-09 | Error names; delete and HEAD are repeatable |
| SA-10 | File bytes pass through worker memory and bandwidth |

### outbox-relay

| ID | What was assumed |
|---|---|
| RLY-01 | How an `unknown` publish outcome is recorded |
| RLY-02 | Exact fields of the message body |
| RLY-03 | Failed rows are re-selected first on every cycle with no backoff |
| RLY-04 | A broker outage keeps a batch transaction open for batch × timeout |
| RLY-05 | Defaults for poll interval, batch size, publish timeout |
| RLY-07 | What makes a row "stuck" |
| RLY-08 | Readiness and effect of the relay being down |
| RLY-09 | Shutdown behaviour |

### worker

| ID | What was assumed |
|---|---|
| WK-01 | The job type is known before the claim from the routing key |
| WK-02 | How a running handler is stopped on lease loss |
| WK-03 | Who decides inline versus file results and who writes the file row |
| WK-04 | Whether `report_progress` writes at once or with the next heartbeat |
| WK-05 | Graceful shutdown; deploys consume attempts |
| WK-07 | Behaviour when the claim itself errors |
| WK-08 | Timeout enforcement and outcome mapping |
| WK-10 | Connection count and pool sizing against Postgres limits |
| WK-11 | No sandbox or resource limit for handlers |

### maintenance

| ID | What was assumed |
|---|---|
| MT-01 | Chore intervals |
| MT-02 | Retry delay for a job whose type is no longer registered |
| MT-03 | Order of row delete and object delete for unused uploads |
| MT-04 | Purge throughput against ingest; no lag alert |
| MT-05 | Retention and grace defaults |
| MT-06 | Number of copies, staggering, repeatable cleanups |
| MT-07 | It touches all organisations without filtering |
| MT-09 | Which counters exist |

### accounts-auth

| ID | What was assumed |
|---|---|
| AA-01 | Source of the organisation name at signup |
| AA-02 | Email and password validation rules |
| AA-03 | Whether signup also logs in |
| AA-04 | User enumeration and timing behaviour |
| AA-05 | Role permissions |
| AA-06 | JWT algorithm and key handling |
| AA-07 | Owner and allowlist of the origin check |
| AA-08 | Key prefix and secret lengths |
| AA-09 | No cap on the number of keys; unbounded list |
| AA-10 | Status and body of "already refreshed" |
| AA-11 | The `role` claim can be stale for about 15 minutes |
| AA-12 | Suspended organisation or disabled user enforcement |
| AA-13 | Argon2 parameters and where it runs |
| AA-14 | Bogus credentials have no limit of their own |
| AA-15 | The access token in memory is exposed to injected script |
| AA-16 | Revoking a key does not stop requests already past verification |

### file-api

| ID | What was assumed |
|---|---|
| FA-01 | Storage key format |
| FA-02 | Pending expiry against link lifetime |
| FA-03 | Which size rule applies (declared size or cap) |
| FA-04 | `get-file` status stays `pending` until a submit checks the file; field list |
| FA-05 | No cap on files per payload |
| FA-07 | Error shapes and existence leaks |
| FA-08 | Content type and file name rules |
| FA-09 | No storage quota per organisation |
| FA-10 | `available` files that no job uses are never removed |
| FA-11 | The result download link function is not named in the sources |
| FA-12 | HEAD runs even for files already `available` |

### job-api

| ID | What was assumed |
|---|---|
| JA-01 | Where the idempotency key is sent |
| JA-02 | Canonical form used for `request_hash` |
| JA-03 | Status codes per outcome |
| JA-04 | Fields of `get-job`; whether the payload is returned; other organisation looks like missing |
| JA-05 | List filters, page sizes, cursor |
| JA-06 | Whether list rows include payload and result |
| JA-08 | Submit without a key is not idempotent after a lost response |
| JA-09 | Polling load of about 1,000 reads per second |
| JA-10 | Handler error text may reach clients |
| JA-12 | Where the payload size cap is checked |

### rate-limiter

| ID | What was assumed |
|---|---|
| RL-01 | Algorithm and atomic increment with expiry |
| RL-02 | Which endpoint belongs to which class |
| RL-03 | Header names and body fields |
| RL-04 | Fail-closed status and body |
| RL-05 | Redis timeouts and behaviour when slow |
| RL-06 | Bogus credentials are unlimited |
| RL-07 | IPv6 and shared-NAT grouping |
| RL-08 | Counters are lost when Redis restarts |
| RL-09 | Default limit values |
| RL-10 | How `Retry-After` is computed |
| RL-11 | No limits on storage volume, queue depth or downloads |

### frontend

| ID | What was assumed |
|---|---|
| FE-01 | Rendering model (browser only versus server-rendered pages) |
| FE-02 | How tabs coordinate a refresh |
| FE-03 | Behaviour on forced login and blocked cookies |
| FE-04 | Create-key double submit and retry |
| FE-05 | Token storage and content-security posture |
| FE-06 | Page layout and fields |
| FE-07 | How 429 and errors are shown |
| FE-09 | Direct API calls versus proxying through Next.js |

### observability

| ID | What was assumed |
|---|---|
| OBS-01 | Which trace id recovery and sweep rows carry |
| OBS-02 | Only the trace id, not the parent span, is stored |
| OBS-03 | Trace sampling and log volume policy |
| OBS-04 | Bounded error-code label |
| OBS-05 | Alert thresholds, routing, Grafana access |
| OBS-06 | `/readyz` dependency list |
| OBS-08 | Telemetry export never blocks requests |
| OBS-09 | Validation of a client-supplied `traceparent` |
| OBS-10 | Personal data in logs |
| OBS-11 | Compatibility of the Grafana stack is unverified |

### platform

| ID | What was assumed |
|---|---|
| PLT-01 | Which process needs which required setting |
| PLT-02 | Secret delivery and rotation |
| PLT-03 | Role and database bootstrap |
| PLT-04 | Startup order, broker coupling and startup time |
| PLT-05 | No ingress or TLS terminator in the topology |
| PLT-06 | Which ports are published |
| PLT-07 | JWT clock-skew leeway |
| PLT-08 | Migration failure and concurrent migrations |
| PLT-09 | Backups, volumes, Redis persistence |
| PLT-10 | Choice of CI tool |

---

## 6. Questions for me (prioritised)

1. **Load.** What are your real targets for submits per second, concurrent running jobs, organisations and retention? Everything in section 3 scales from my numbers.
2. **Handler execution and shutdown.** Do handlers run in a thread or a child process, how is a timeout enforced, and should a deploy that stops a worker consume an attempt? (F-04, F-05)
3. **Connections.** How many worker processes will the largest pool have? Should PgBouncer or one shared connection per process be in the first version? (K-01)
4. **What sits in front of the API in production,** and should the trusted-proxy setting and a limit on bogus credentials move into Phase 1? (F-06, F-07)
5. **Result files.** Who creates them and how are they read back? This blocks the Phase 1 sample handler. (F-08)
6. **Idempotent repeats.** Do you accept looking up the key before any file work, and what status should a repeat return? (F-01)
7. **Delivery settings.** Do you confirm persistent messages, a prefetch of 1, and cancel-before-ack? (F-11)
8. **Retention and file cleanup.** Measured from creation or from finish, and which chore deletes files and objects? (F-09, F-20)
9. **Roles and scopes.** Which roles may create or revoke keys, which scope and credential kind does each endpoint need, and what do a suspended organisation and a disabled user mean? (F-13, F-14)
10. **Poison outbox rows.** Should a row that fails N times fail its job in Phase 1, or be parked and alerted on? (F-02)

---

## 7. Proposed changes (not applied)

Each snippet is a suggestion for a change to `ARCHITECTURE.md`, `DATABASE.md` or `NOTEPAD.md`. None has been made. [ASSUMPTION A-01]

### 7.1 `ARCHITECTURE.md` §5, steps 2 and 3 (F-01)

```text
2. The API checks the key, scopes and request rate limits, then validates the payload
   against the job type's input schema. If an idempotency key was given, the API looks it up
   (read only) and, if a job exists for it, returns that job at once. Otherwise, before any
   transaction or lock, it checks each file ... (unchanged)
3. In one database transaction the API takes the per-organisation lock, checks the
   idempotency key again, ... (unchanged)
```

### 7.2 `DATABASE.md` §4.11, relay rules (F-02, F-03, F-19)

```text
- On a failed publish the relay sets run_at = now() + backoff (capped) and raises
  publish_attempts, so a failing row leaves the head of the queue.
- The relay stops a cycle after K consecutive failed publishes.
- Index for cleanup: CREATE INDEX outbox_published_idx ON outbox (id) WHERE published_at IS NOT NULL;
```

### 7.3 `DATABASE.md` §5, new operation (F-05)

```text
| Release (worker shutting down) | Guarded by the lease token. Set retrying, run_at = now(),
  attempts = attempts - 1, close the job_attempts row as released, insert an outbox row
  (reason = recovery) | One transaction. A planned stop does not consume an attempt |
```

### 7.4 `ARCHITECTURE.md` §11, delivery settings (F-11, F-21)

```text
- Messages are published persistent. Consumers use a prefetch of 1. A worker cancels its
  consumers before acking the message that fills its last place. The delivery object carries
  the routing key, the body, the headers and the redelivered flag.
```

### 7.5 `ARCHITECTURE.md` §12, health (F-17)

```text
- /readyz reports only the dependencies a process cannot work without: Postgres for the API,
  the relay, workers and maintenance; the broker only for the relay and workers; Redis and
  storage are reported but do not make a process unready.
```

### 7.6 `ARCHITECTURE.md` §4, topology (F-07)

```text
| ingress | TLS termination and reverse proxy in front of api, frontend and storage. Sets the
  forwarded headers that the trusted-proxy setting reads |
```

### 7.7 `ARCHITECTURE.md` §9 and §17, rate-limit wording (F-33)

```text
Four request-rate limit classes live in Redis (API key, organisation, login and signup,
refresh and logout). The fifth limit, active jobs per organisation, is counted in Postgres.
```

### 7.8 `ARCHITECTURE.md` §15, extra tuning settings (F-23)

```text
relay poll interval, relay batch size, relay publish timeout, maintenance interval and batch
size per chore, API-key last-used write interval, progress write interval, storage HEAD
timeout, Redis timeout, maximum files per payload, per-organisation storage quota
```

### 7.9 `DATABASE.md` §10, files cleanup (F-09)

```text
| files not referenced by job_files or jobs.result_file_id for a grace period | Delete the
  object, then the row. Run in the maintenance container, claimed with SKIP LOCKED |
| files with status available and no job_files row, older than a limit | Same as above |
```

### 7.10 `ARCHITECTURE.md` §10, one authority for max attempts (F-12)

```text
next-retry-delay takes the job's max_attempts and retry_delays as stored on the job at
submit. The definition is read only when a job is created.
```

### 7.11 `NOTEPAD.md`, supersession notes (F-30)

```text
D3  > Superseded in part by D32: the frontend uses an access token plus a refresh cookie.
D7  > Superseded in part by D32: "Sessions are httpOnly cookies" no longer holds.
D9  > Superseded in part by D32: same.
D10 > Superseded in part: no dead-letter queue (D25); run_at is used from Phase 1 (D24).
D15 > State machine bullet superseded: a retry goes retrying -> running, never back to queued.
D16 > Superseded by D29: the active-jobs count is not applied through the RateLimiter.
D17 > Superseded by D29 for the active-jobs row; refresh and logout were added by D40.
D27 > The "Finds" bullet and the outbox index are superseded by D38.
```
