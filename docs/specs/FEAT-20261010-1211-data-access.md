# FEAT-20261010-1211: data access (the PostgreSQL adapter)

Status: **draft for approval**. Working branch: `feat-20261010-1211-data-access`, from `master`. Depends on: `FEAT-1204` (schema, merged), `FEAT-1210` (domain, merged), `FEAT-1212` (job types: the type name, version and `max_attempts` come from a definition, so the registry should land first). Used by: the API, worker and maintenance tasks, and the isolation contract test (`FEAT-1226`).

## 1. What this builds and why

The only code that writes SQL. It turns the design in `DATABASE.md` section 5 and `data-access.md` into repository interfaces (ports) and a PostgreSQL implementation, so the rest of the system calls named operations such as "claim this job" and never touches a table. Every transaction boundary, lock and guard lives here. The domain tells it what is allowed (`FEAT-1210`); it does not decide business rules.

## 2. What I checked

| Fact | Source |
|---|---|
| The operations, their parameters, their guards and their workflows (submit, claim, heartbeat, finish, retry, fail, refresh rotation, recovery, sweep, cleanups, purge) are written out step by step | `data-access.md` sections 2 and 5 |
| Every read or write on organisation-owned data filters on `organisation_id`; "now" is the database clock; results are typed outcomes, not HTTP codes | `data-access.md` section 2, `DATABASE.md` section 2 |
| The schema, indexes, CHECKs and table settings exist and are tested (`FEAT-1204`); the state table and `source_statuses` exist (`FEAT-1210`) | merged code |
| Lock order in submit: organisation advisory lock, then the file rows `FOR SHARE`, then the inserts; storage checks happen before the transaction (D36) | `ARCHITECTURE.md` section 5 |
| Findings that change the **outbox** operations: F-02 (a row that cannot be published must leave the head of the queue) and F-03 (the relay must not hold a transaction while the broker is down) | `findings.md` |
| Open: who removes the `files` rows and objects of files that jobs used (conflict C-05, open question 8) | `findings.md` |
| 21 assumptions (DA-01 to DA-19) were left open by the design; section 3.4 settles each | `findings.md` |

## 3. Proposal

### 3.1 What is in this task and what is not

**In:**
1. **Accounts:** create user with organisation, find password identity, record login, insert, rotate and revoke refresh tokens, read membership, API key rows (create, find by prefix, touch last used, list, revoke).
2. **Files:** create, get, mark available.
3. **Jobs for the API:** submit (the full transaction), get, list, list attempts.
4. **Jobs for the worker:** claim, heartbeat, finish with success, retry, fail.
5. **Maintenance:** recover expired leases, sweep waiting jobs, clean published outbox rows, clean refresh tokens, clean pending files, purge finished jobs.

**Not in this task, and why:**
- **The outbox relay operations** (fetch due rows, mark published, record a publish failure, close the batch). Findings F-02 and F-03 change their shape (a poison row must leave the head; no long transaction while the broker is down), and those are open question 10 of `ISS-1155`. They move into the relay spec (`FEAT-1215`). The submit, retry, recovery and sweep operations here do insert outbox rows, as designed.
- **Removing the files that jobs used** (C-05, question 8): no operation until that is decided. Purging jobs leaves their `files` rows, as the schema forces.
- **Who creates result files and when** (question 5): `create_file` accepts both kinds; callers come with the worker and file API specs.

### 3.2 Ports (`qfe/ports/repositories.py`) and outcomes

Five interfaces, each used by different callers so a process only sees what it needs: `AccountRepository`, `FileRepository`, `JobRepository` (API side), `JobExecutionRepository` (worker side), `MaintenanceRepository`. Expected business outcomes are typed values, not exceptions and not HTTP codes, for example for submit: `Created(job_id)`, `Existing(job)`, `IdempotencyConflict`, `CapExceeded`, `FileUnavailable(file_id)`; for worker writes: `Ok` or `LeaseLost`; for refresh rotation: `Rotated(new_id)`, `AlreadyRefreshed`, `ReuseDetected`, `FamilyExpired`, `Revoked`, `Expired`. Real failures (database down) stay exceptions. The interfaces carry only plain data (small frozen dataclasses), never SQLAlchemy objects.

### 3.3 The PostgreSQL implementation (`qfe/adapters/postgres/`)

- `database.py`: one `Database` object that owns the async engine for a process. Pool size, overflow and wait time are settings (`QFE_DB_POOL_SIZE` 10, `QFE_DB_POOL_OVERFLOW` 5, `QFE_DB_POOL_TIMEOUT_SECONDS` 30), **provisional until open question 3 (connections) is settled**; there is no PgBouncer (D43), so a process holds its own connections.
- One module per interface (`accounts.py`, `files.py`, `jobs.py`, `execution.py`, `maintenance.py`), written with SQLAlchemy Core and explicit SQL where a statement needs `FOR UPDATE SKIP LOCKED`, `RETURNING` or a CTE. Each operation opens its own transaction and finishes it; there is no hidden session shared between calls.
- **Status changes use the domain table:** every `WHERE status IN (...)` is built from `source_statuses(event)`. A test checks each operation against every status (3.4 and section 4), so SQL and table cannot drift.
- The submit lock key comes from Postgres itself: `pg_advisory_xact_lock(hashtextextended(:organisation_id, 0))`. Lease tokens come from `gen_random_uuid()`. So the adapter needs no random source and no extra port.
- Retry delays arrive as durations (`timedelta`); SQL writes `now() + interval`. Recovery asks the caller for the delay and uses `decide_after_failure` from the domain for retry-or-fail, so it behaves exactly like the worker.

### 3.4 How each open assumption is settled

| # | Question the design left open | Decision |
|---|---|---|
| DA-01 | Error type names | typed outcome values, named as in 3.2 |
| DA-02 | How the organisation slug is made | the **caller** passes the slug (the accounts task owns the rule); the repository returns `SlugTaken` |
| DA-04 | API key prefix collision | repository returns `PrefixTaken`; the caller picks a new prefix |
| DA-05 | Does key lookup return the organisation status | **yes**, so authentication can refuse a suspended organisation |
| DA-06 | Where the "last used" throttle lives | **in SQL**: `UPDATE ... WHERE last_used_at IS NULL OR last_used_at < now() - :interval` (no process memory, so it also holds with several API copies) |
| DA-07 | `mark_available` and `expires_at` | **clears `expires_at`**. Reason: otherwise a file marked available but used a day later would be rejected as "expired" at submit; cleanup only deletes `pending` files, so an available file's life follows retention (open question 8) |
| DA-08 | List filters | status plus keyset cursor and limit; other filters later |
| DA-09 | Attempts and isolation | the query joins `jobs` and filters on `organisation_id` |
| DA-10 | Why a claim is refused | outcome `Refused(reason)` with `NOT_FOUND`, `NOT_DUE` or `NOT_CLAIMABLE(status)`, found by one follow-up read after a zero-row update |
| DA-11 | Recovery result | a list of `(job_id, decision)` where the decision is the domain event (`RETRY` or `FAIL`) |
| DA-12 | Pending file cleanup result | the storage keys of the rows deleted, so the caller deletes the objects |
| DA-13 | Defaults on insert | `attempts` 0, `sweep_count` 0, `run_at` and `last_enqueued_at` = `now()` |
| DA-14 | Refresh rotation locking | the presented row is locked `FOR UPDATE` |
| DA-16 | Lock order | advisory lock, then file rows `FOR SHARE`, then inserts. No other operation takes the advisory lock, so no cycle is possible |
| DA-17 | Repeating operations | revoking a family or a key, and marking files available, are safe to repeat |
| DA-18, DA-19 | Key cache, unbounded key list | no cache now; `list_api_keys` takes a limit (default 100, maximum 500) |
| DA-03, DA-15 | Create user atomic; failure counts lost on rollback | create user with organisation is one transaction; DA-15 belongs to the relay operations (not here) |

## 4. Tests (integration, against the Compose test Postgres, one database cloned per test)

- **Every operation:** the normal case, each guard, and each typed outcome.
- **Organisation isolation:** for every operation that takes an organisation id, a second organisation's id returns nothing and changes nothing (this also feeds the isolation contract test in `FEAT-1226`).
- **State matrix:** for every operation that changes a job's status and every one of the six statuses, the operation succeeds exactly when `source_statuses` says it may and is refused otherwise.
- **Concurrency (real parallel connections):** two claims of one job give exactly one winner; 20 simultaneous submits with the same idempotency key give one created job and 19 `Existing`; 20 simultaneous submits for an organisation with a cap of 5 give exactly 5 created and 15 `CapExceeded` (the cap is exact); two simultaneous refreshes of one token give one `Rotated` and one `AlreadyRefreshed`; a refresh after the reuse window revokes the whole family; refresh after `family_expires_at` is refused.
- **Lease rules:** after recovery has taken a job, the old worker's heartbeat, finish, retry and fail all return `LeaseLost` and change nothing; recovery fails the job when `attempts >= max_attempts` and otherwise retries it with a delay and one outbox row (reason `recovery`), the attempt closed as `lease_lost`.
- **Sweep:** waits 5 minutes, then 10, 20, 40, capped at 1 hour, using `sweep_count`; skips jobs that still have an unpublished outbox row; deleting old outbox rows never resets the wait.
- **Purge and cleanup:** purge touches only final states and deletes by id range in batches; cascades remove attempts, outbox rows and job-file links; pending file cleanup returns the keys; refresh token cleanup keeps live tokens.
- **Submit details:** files must be `available`, owned by the organisation and unexpired, else `FileUnavailable`; one job row, the job-file links and one `submit` outbox row appear together or not at all (a forced failure in the middle leaves nothing).
- Database-clock check: moving no application clock changes any result.

## 5. Check for the same problem elsewhere

Lateral: every statement that reads or writes organisation-owned data gets the organisation filter, checked by the isolation tests for all of them and not for a sample. Causal depth: a job can be corrupted by a wrong guard (state matrix), by two writers racing (concurrency tests), by a stale worker (lease tests) or by a cap or idempotency race (submit tests); each cause has its own test group.

## 6. Out of scope

Relay operations (`FEAT-1215`), file cleanup for used files (after question 8), the job and account HTTP APIs, the rate limiter, PgBouncer and the advisory lock under it (`WISH-1310`), partitioning.

## 7. Questions for you

1. The four outbox relay operations move to the relay spec, because the open findings F-02 and F-03 change them. OK?
2. `mark_available` clears `expires_at` (DA-07). OK?
3. The "last used" throttle for API keys is done in SQL (DA-06). OK?
4. Pool defaults 10 plus 5 are provisional until we settle open question 3 (connections). OK?
