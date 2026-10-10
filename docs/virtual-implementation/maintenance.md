# maintenance

Part 11 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** Runs the background chores that nothing else owns: lease recovery for jobs whose worker died, the safety-net sweep for jobs with no message on the way, and the cleanups and purges that keep tables from growing forever. [ARCH: Containers (Docker Compose)] [NOTEPAD: D19] It is a separate container, same image as the API with a different command, so a slow cleanup can never delay publishing. [ARCH: 4. System overview]

**Does not do:**
- Publish messages. It only inserts outbox rows, which the relay publishes. [ARCH: 11. Reliability and delivery]
- Choose retention values or intervals. They are configuration. [DB: 10. Retention and cleanup]
- Delete files that jobs used, nor their `files` rows. No chore for that is described. [CONFLICT C-05]
- Delete organisations or users. [DEFERRED: organisation and user deletion flow]
- Partition tables. [DEFERRED: time partitioning of jobs]

## 2. Interfaces provided

**To other parts: None.** It exposes no interface that another part calls. Its effects are database rows (outbox rows written through [data-access#recover-expired-leases] and [data-access#sweep-waiting-jobs]) and the outputs below. [ARCH: Containers (Docker Compose)]

Observable outputs:

| Output | Content | Source |
|---|---|---|
| Sweep warning log and metric | Each sweep re-queue logs a warning, increments a metric and can alert, because it should be rare and usually means a bug | [ARCH: 11. Reliability and delivery] [NOTEPAD: D27] |
| Recovery and cleanup counts | Which counters exist is not listed beyond "sweep re-queues" | [ARCH: 12. Observability] [ASSUMPTION MT-09] |
| Run settings | Interval and batch size per chore, retention and grace values, sweep batch cap | [ARCH: 15. Configuration] [ASSUMPTION MT-01] |

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| `data-access` | [data-access#recover-expired-leases] | Recovers or fails running jobs whose lease expired |
| `data-access` | [data-access#sweep-waiting-jobs] | Re-queues waiting jobs that have no message on the way |
| `data-access` | [data-access#cleanup-published-outbox], [data-access#cleanup-refresh-tokens], [data-access#cleanup-pending-files], [data-access#purge-finished-jobs] | The four cleanups |
| `job-type-registry` | [job-type-registry#next-retry-delay] | Supplies the `delay_for` function that recovery needs, so a job that crashes its worker is not retried at once |
| `storage-adapter` | [storage-adapter#delete-object] | Deletes the objects of purged unused uploads |
| `observability` | [observability#trace-context] | Logs and metrics |
| `platform` | [platform#startup-config-validation] | Intervals, batch sizes, retention and grace values |

Sources for the table: [DB: 5. How the main operations touch the database] [DB: 10. Retention and cleanup] [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: Containers (Docker Compose)]

## 4. Data

**Reads and writes (through `data-access`):**

| Table | Chore | Source |
|---|---|---|
| `jobs` | Recovery sets `failed` or `retrying`; sweep raises `sweep_count` and `last_enqueued_at`; purge deletes finished rows | [DB: jobs; §5 Recover] [DB: jobs.sweep_count] [DB: jobs.last_enqueued_at] |
| `job_attempts` | Recovery closes the open attempt as `lease_lost`; purge cascades | [DB: job_attempts.outcome] |
| `outbox` | Recovery and sweep insert rows; cleanup deletes published rows; the sweep checks for unpublished rows | [DB: outbox.reason] [DB: 10. Retention and cleanup; outbox] |
| `refresh_tokens` | Cleanup deletes expired or revoked rows after a grace period | [DB: 10. Retention and cleanup; refresh_tokens] |
| `files` | Purge deletes `pending` rows past `expires_at` | [DB: files.expires_at] [DB: 10. Retention and cleanup; files] |
| `job_files` | Removed by cascade when a job is purged | [DB: job_files.job_id] |

**Who else touches them:** the API, the worker and the relay, as listed in the data ownership map in [overview.md](overview.md) section 5. [DB: 5. How the main operations touch the database]

## 5. Internal workflow

Each chore runs on its own schedule, claims its rows with `SKIP LOCKED`, and works one transaction per job or one batch at a time. The intervals are not stated. [DB: 10. Retention and cleanup] [ARCH: Containers (Docker Compose)] [ASSUMPTION MT-01]

### 5.1 Lease recovery

1. Call [data-access#recover-expired-leases] with a batch size and a `delay_for` function. [DB: jobs; §5 Recover]
2. For each running job with an expired lease: if `attempts >= max_attempts`, mark it `failed`; otherwise mark it `retrying` with `run_at = now() + delay` and insert an outbox row (`reason = recovery`). The open attempt is closed as `lease_lost` either way. [DB: jobs; §5 Recover] [ARCH: 11. Reliability and delivery]
3. `delay_for(job)` is [job-type-registry#next-retry-delay] for the job's type and attempt number. [ARCH: 10. Job types and handlers (how new work plugs in)] If the type is no longer registered in the maintenance image, no delay can be computed. [ASSUMPTION MT-02]

### 5.2 Safety-net sweep

1. Call [data-access#sweep-waiting-jobs] with a bounded batch. [ARCH: 11. Reliability and delivery]
2. It re-queues jobs that are `queued` or `retrying`, whose `run_at` and `last_enqueued_at` are older than `5 minutes * 2^sweep_count` (capped at 1 hour) and that have no unpublished outbox row. [DB: jobs; §5 Sweep] [NOTEPAD: D38]
3. Log a warning, count a metric and allow an alert for each job swept. [ARCH: 11. Reliability and delivery]

### 5.3 Cleanups

1. **Published outbox rows:** delete in small batches after a delay of hours to a day, whatever state the job is in. [DB: 10. Retention and cleanup; outbox]
2. **Refresh tokens:** delete expired or revoked rows after a grace period. [DB: 10. Retention and cleanup; refresh_tokens]
3. **Unused uploads:** delete `files` rows with `status = pending` past `expires_at`, then delete their storage objects. The order between the row delete and the object delete is not stated. [DB: 10. Retention and cleanup; files] [ASSUMPTION MT-03]

### 5.4 Job purge

1. Call [data-access#purge-finished-jobs] with the retention cut-off. [DB: 10. Retention and cleanup; jobs]
2. It deletes in batches by `id` range, only rows in `succeeded`, `failed` or `cancelled`, so a stuck job is never deleted from under a worker. [DB: 10. Retention and cleanup; jobs]
3. `job_attempts`, `outbox` and `job_files` rows go with the job by cascade. [DB: job_attempts.job_id] [DB: outbox.job_id] [DB: job_files.job_id]
4. The rule that files used by jobs are "removed with the last job that uses them" has no step here. [DB: 10. Retention and cleanup; files] [CONFLICT C-05]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| A chore crashes mid-batch | Each job or batch is its own transaction; finished ones are kept, the rest are picked up next run | None | [DB: jobs; §5 Recover] |
| Database down | All chores stop; nothing is recovered, swept or purged | Backlog of work | [DB: 1. Principles] |
| Storage down during unused-upload cleanup | The object delete fails | A `files` row deleted with its object still present, or the reverse, depending on order | [ASSUMPTION MT-03] |
| Recovery for a job whose type is not registered | No retry delay can be computed | Job stays `running` with an expired lease, or fails | [ASSUMPTION MT-02] |
| Sweep finds jobs of a type nobody consumes | It re-queues them with a longer wait each time | Extra messages waiting in that type's queue | [DB: jobs; §5 Sweep] [DEFERRED: maximum wait for a type with no workers] |
| Purge falls behind ingest | Table grows; no metric or alert for purge lag is described | Growing `jobs` table | [DB: 11. Growth plan] [ASSUMPTION MT-04] |
| A late heartbeat arrives while recovery runs | Recovery re-checks inside its transaction; if the heartbeat extended the lease first, recovery skips the job; if recovery committed first, the heartbeat gets `lease-lost` | Either outcome is consistent | [DB: jobs; §5 Recover] [DB: jobs.lease_token] |

## 7. Concurrency and idempotency

- Several copies can run at the same time because each chore claims rows with `SKIP LOCKED`. [ARCH: Containers (Docker Compose)] [NOTEPAD: D19]
- Recovery re-checks its conditions after taking the row lock. [DB: jobs; §5 Recover]
- A sweep message that duplicates an existing one is harmless: the claim refuses a job that is running, finished or not yet due. [ARCH: 11. Reliability and delivery]
- Cleanup deletes are repeatable: a second run finds nothing more to delete. [ASSUMPTION MT-06]
- How many copies run, and whether their schedules are staggered, is not stated. [ASSUMPTION MT-06]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Recovery scan:** looks at every running job each run, about 2,000 at L-02, using the partial index on running jobs. [DB: jobs; Indexes] [ASSUMPTION L-02]
- **Sweep scan:** looks at every waiting job each run, using the partial index on `run_at` for `queued` and `retrying`; a deep backlog makes this scan large. A batch cap limits the work per run. [DB: jobs; Indexes] [ARCH: 11. Reliability and delivery]
- **Purge volume:** at L-01 about 4.3 million jobs finish per day, and each purge also deletes its attempts and outbox rows by cascade. The purge must delete faster than jobs are created or the table keeps growing. [DB: 10. Retention and cleanup; jobs] [ASSUMPTION L-01] [ASSUMPTION MT-04]
- **Table size:** about 130 million `jobs` rows at 30 days of retention. [ASSUMPTION L-05]
- **Write amplification:** cleanups create dead tuples, and autovacuum thresholds are lowered on `jobs`, `job_attempts` and `outbox`. [DB: 9. Performance and tuning plan]
- **Batches are small on purpose** to keep locks short and WAL manageable. [DB: 10. Retention and cleanup]

## 9. Security

- No external callers. [ARCH: Containers (Docker Compose)]
- It runs with the `qfe_app` role, which can delete data but not change the schema. [DB: 9. Performance and tuning plan] A bug or a wrong retention value can delete data; the purge is limited to final states for that reason. [DB: 10. Retention and cleanup; jobs]
- It uses storage credentials to delete objects. [ARCH: 15. Configuration]
- It touches rows of every organisation by design; it does not filter by organisation. [ASSUMPTION MT-07]

## 10. Open questions and deferred items

- A chore for the `files` rows and objects of files that jobs used. [CONFLICT C-05]
- Organisation and user deletion, and erasing personal data. [DEFERRED: organisation and user deletion flow]
- Audit log of key and user actions. [DEFERRED: audit log]
- Maximum wait for a type with no workers. [DEFERRED: maximum wait for a type with no workers]
- Partitioning would replace row deletes with dropping partitions. [DEFERRED: time partitioning of jobs]
- Intervals, batch sizes, retention and grace values, how many copies run, and a purge-lag alert. [ASSUMPTION MT-01] [ASSUMPTION MT-04] [ASSUMPTION MT-05]
