# worker

Part 10 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** Takes "job is ready" messages from the queues of the job types it serves, claims the job in Postgres, runs the handler, keeps the lease alive with heartbeats, and writes the outcome: success, retry or failure. [ARCH: 5. Life of a job] [ARCH: Containers (Docker Compose)] It runs as one or more pools; each pool is a set of containers with the same `WORKER_JOB_TYPES` and its own concurrency. [ARCH: Worker pools and concurrency (D35)]

**Does not do:**
- Publish retries to RabbitMQ. A retry is a status change plus a new outbox row, and the relay publishes it. [NOTEPAD: D22]
- Recover jobs whose worker died, or sweep lost messages. That is `maintenance`. [ARCH: 11. Reliability and delivery]
- Decide how long to wait before a retry. [job-type-registry#next-retry-delay] returns the duration. [ARCH: 10. Job types and handlers (how new work plugs in)]
- Check API credentials or rate limits. [ARCH: Containers (Docker Compose)]
- Run third-party workers. [DEFERRED: external workers (wishlist)]

## 2. Interfaces provided

### 2.1 `handler-context`

The object passed to a handler's `handle(context, payload)`. [ARCH: 10. Job types and handlers (how new work plugs in)]

| Field | Meaning | Source |
|---|---|---|
| job id | Id of the job | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| trace id | Trace id of the job, from `jobs.trace_id` | [ARCH: 10. Job types and handlers (how new work plugs in)] [DB: jobs.trace_id] |
| organisation | The owning organisation | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| attempt number | Which try this is | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| storage adapter | [storage-adapter#read-object] and [storage-adapter#write-object] | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| `report_progress(percent)` | Reports progress from 0 to 100 | [ARCH: 10. Job types and handlers (how new work plugs in)] [DB: jobs.progress] |
| logger | A logger already tagged with the trace id | [ARCH: 10. Job types and handlers (how new work plugs in)] |

Whether `report_progress` writes at once or rides on the next heartbeat is not stated; progress writes are throttled to once every few seconds. [DB: 8. Write load and size limits] [ASSUMPTION WK-04]

### 2.2 `consume-loop`

The behaviour of the worker process, which is what [queue-adapter#consume-queue] calls into through `on_message`.

| Setting | Meaning | Required | Source |
|---|---|---|---|
| `WORKER_JOB_TYPES` | Job types this pool serves; `*` means every type the worker has code for; missing means the worker does not start; an unknown listed type stops startup | R | [ARCH: Worker pools and concurrency (D35)] [ARCH: 15. Configuration] |
| concurrency | Jobs run at the same time in one process; for example 1 for `ocr.extract` | R | [ARCH: Worker pools and concurrency (D35)] |
| lease length and heartbeat interval | Tuning values; the interval is for example a third of the lease | R | [DB: 8. Write load and size limits] [ARCH: 15. Configuration] |
| short wait before handing a message back | Tuning value | R | [ARCH: 11. Reliability and delivery] |

### 2.3 `worker-metrics`

Job duration by type, retries, and `jobs_failed_total` by job type and error code. `job_type` is a safe label; `org_id` and `job_id` are not. [ARCH: 12. Observability] Whether a worker has an HTTP port for `/metrics` and `/healthz` is not stated. [ASSUMPTION A-12]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| `queue-adapter` | [queue-adapter#consume-queue], [queue-adapter#ack-message], [queue-adapter#nack-requeue], [queue-adapter#declare-queue] | Receives messages, acks after the claim, hands back messages that cannot start, declares queues at startup |
| `data-access` | [data-access#claim-job], [data-access#heartbeat-job], [data-access#finish-job-success], [data-access#retry-job], [data-access#fail-job] | All job state changes |
| `job-type-registry` | [job-type-registry#get-job-type], [job-type-registry#list-registered-types], [job-type-registry#next-retry-delay], [job-type-registry#permanent-error], [job-type-registry#handler-signature] | Finds the handler's settings, expands `*`, chooses a retry delay, tells permanent errors from others |
| `storage-adapter` | [storage-adapter#read-object], [storage-adapter#write-object] | Available to handlers through the context |
| `data-access` | [data-access#create-file-row] | To record a result file; who does this is not stated |
| `observability` | [observability#trace-context] | Continues the trace of the job |
| `platform` | [platform#startup-config-validation] | Settings above |

Sources for the table: [ARCH: 5. Life of a job] [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: 11. Reliability and delivery] [ARCH: 15. Configuration] [ASSUMPTION A-11]

## 4. Data

**Reads:** the claimed job (`type`, `payload`, `organisation_id`, `trace_id`, `attempts`, `max_attempts`) returned by the claim. [DB: jobs]

**Writes (all through `data-access`):** `jobs` (status, lease fields, progress, result, error, `run_at`, `finished_at`), `job_attempts` (insert at claim, close at the end), `outbox` (a retry row). [DB: jobs; §5] [DB: job_attempts] [DB: outbox.reason]

**Who else touches them:** the API inserts jobs; `maintenance` recovers, sweeps and purges; the relay reads outbox rows. [DB: jobs; §5]

## 5. Internal workflow

### 5.1 Startup

1. Require `WORKER_JOB_TYPES`; stop if it is missing. [ARCH: Worker pools and concurrency (D35)]
2. Expand `*` through [job-type-registry#list-registered-types]; stop if a listed type has no definition or handler. [ARCH: Worker pools and concurrency (D35)]
3. Declare the queue of each served type. [ARCH: 11. Reliability and delivery]
4. Start consuming those queues. [ARCH: Worker pools and concurrency (D35)]

### 5.2 One message

1. Receive the delivery. If the body is unreadable or has no job id, ack it, log an error with the size only, and count a metric. [ARCH: 11. Reliability and delivery]
2. If the message is for a type the worker has no handler for (misconfiguration), do not claim: ack, log an error, count a metric. The sweep re-queues it. [ARCH: 11. Reliability and delivery] [NOTEPAD: D26] The type is known from the routing key, since the claim has not yet returned it. [ASSUMPTION WK-01]
3. Wait for a free place. If none frees within the short wait, `nack-requeue` the message. [ARCH: 11. Reliability and delivery]
4. Call [data-access#claim-job]. On `refused(reason)`, ack and log the reason (finished, owned by someone else, or not due yet). This is not an error. [ARCH: 5. Life of a job]
5. On `claimed`, the transaction has committed: ack the message, then start the handler. [ARCH: 5. Life of a job]
6. If the claim call itself fails (for example the database is unreachable), the message is still unacked and will be delivered again. Whether the worker waits, nacks or drops the connection is not stated. [ARCH: 5. Life of a job] [ASSUMPTION WK-07]

### 5.3 Running the handler

1. Build the [worker#handler-context] and call `handle(context, payload)` for the job type. [ARCH: 10. Job types and handlers (how new work plugs in)]
2. In parallel, send a heartbeat at the interval through [data-access#heartbeat-job]. If the answer is `lease-lost`, stop the handler and write nothing more. [ARCH: 11. Reliability and delivery] How a running handler is stopped is not stated. [ASSUMPTION WK-02]
3. The definition's `timeout` applies; what enforces it and how it maps to the `timeout` outcome is not stated. [ARCH: 10. Job types and handlers (how new work plugs in)] [DB: job_attempts.outcome] [ASSUMPTION WK-08]

### 5.4 Outcome

1. **Success:** call [data-access#finish-job-success] with the result, or with `result_file_id` if the result is a file or too large for the row. [ARCH: 5. Life of a job] [DB: 8. Write load and size limits] Who decides inline versus file, and who writes the file row, is not stated. [ASSUMPTION WK-03]
2. **`permanent-error`:** call [data-access#fail-job] at once with outcome `permanent_error`. [ARCH: 10. Job types and handlers (how new work plugs in)]
3. **Any other exception, or timeout, with attempts left (`attempts < max_attempts`):** get the delay from [job-type-registry#next-retry-delay] and call [data-access#retry-job]. [ARCH: 5. Life of a job] [ARCH: 10. Job types and handlers (how new work plugs in)]
4. **Any other exception, or timeout, with attempts used up:** call [data-access#fail-job]. [ARCH: 5. Life of a job]
5. If any of these returns `lease-lost`, do nothing further. The newer attempt is untouched. [ARCH: 11. Reliability and delivery]
6. Free the place and resume consumers. [ARCH: 11. Reliability and delivery]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Crash before the claim commits | The message was never acked and is delivered again | None | [ARCH: 5. Life of a job] |
| Crash after the claim | The lease expires and recovery takes over | `running`, open attempt | [ARCH: 5. Life of a job] |
| Ack lost after the claim | Redelivery; the claim is refused and the worker acks | None | [ARCH: 5. Life of a job] |
| Handler raises | Retry or failure as in 5.4 | `retrying` or `failed` | [ARCH: 5. Life of a job] |
| Handler blocks the worker's event loop | The heartbeat cannot run, the lease expires, and recovery requeues a job that is still running | Two runs of one job possible | [ARCH: 11. Reliability and delivery] [ASSUMPTION A-13] |
| Heartbeat answer `lease-lost` | Handler stopped, no more writes | Newer attempt owns the job | [ARCH: 11. Reliability and delivery] |
| Worker stopped on purpose (for example a deploy) | The lease runs out and the attempt counts. Nothing says the worker finishes or hands back its job | An attempt consumed without a handler failure | [DB: jobs.attempts] [ASSUMPTION WK-05] |
| Finish, retry or fail write fails because the database is down | The handler's work is done but unrecorded; the lease expires and the job is recovered | Possible repeat run | [ARCH: 11. Reliability and delivery] |
| Message for an unknown type | Acked and logged; the sweep re-queues it | Job waits | [NOTEPAD: D26] |
| All places busy longer than the consumer timeout while holding a delivered message | The channel is closed by RabbitMQ unless the message is handed back first | Messages redelivered | [NOTEPAD: Phase 0 verification results] [ARCH: 11. Reliability and delivery] |

## 7. Concurrency and idempotency

- Concurrency is per pool and per process: 1 for OCR, tuned by load testing for others. Separate pools stop a flood of slow jobs from using every worker. [ARCH: Worker pools and concurrency (D35)]
- The worker consumes only while it has free concurrency, and may briefly hold at most one delivered, unclaimed message per queue. [ARCH: 11. Reliability and delivery]
- Two workers receiving the same job: the claim lets one win; the other acks and logs. [ARCH: 5. Life of a job]
- Handlers must be safe to run twice. [ARCH: 10. Job types and handlers (how new work plugs in)]
- Every write after the claim carries the lease token, so a worker that lost its lease cannot overwrite a newer attempt. [ARCH: 11. Reliability and delivery]
- A worker serving several types shares one concurrency limit across its queues. [ARCH: 11. Reliability and delivery]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Heartbeat load:** with 2,000 jobs running and a 20-second interval, about 100 job updates per second. [DB: 8. Write load and size limits] [ASSUMPTION L-02] [ASSUMPTION L-03]
- **Process count:** at concurrency 1, 2,000 running jobs means 2,000 worker processes in the heavy pools. [ARCH: Worker pools and concurrency (D35)] [ASSUMPTION L-02]
- **Connections:** each process needs at least one Postgres connection and one broker connection. For 2,000 processes that is thousands of each, while PgBouncer "is not needed in the first version". [NOTEPAD: Phase 0 verification results] [ASSUMPTION WK-10]
- **Per-job database work:** one claim (update plus insert), N heartbeats, one outcome transaction. [DB: 5. How the main operations touch the database]
- **Payload in memory:** the claim returns the payload, which can be large up to the cap. [DB: 8. Write load and size limits]
- **Cancel and restart of consumers** at every job when concurrency is 1. [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-05]
- **File bytes** pass through the worker's memory and network when handlers read or write. [ASSUMPTION SA-10]

## 9. Security

- No external callers. It reaches Postgres, RabbitMQ and storage with configured credentials. [ARCH: 15. Configuration]
- The organisation comes from the claimed job and not from the message; the message holds only a job id. [DB: outbox.body] [ARCH: 10. Job types and handlers (how new work plugs in)]
- Handlers are our own code, loaded only by workers. [ARCH: 6. Code structure and the adapter rule] [NOTEPAD: D4]
- Handlers process tenant-supplied documents inside the worker process, with no sandbox or per-job resource limit described. [ASSUMPTION WK-11]
- Logs record ids and sizes, not payload content. [ARCH: 16. Security notes]

## 10. Open questions and deferred items

- Manual retry, cancel and priorities. [DEFERRED: manual retry of a failed job] [DEFERRED: Phase 2 features: priorities, delayed jobs, cancel, completion webhooks]
- Handler version versus `jobs.type_version` mismatch. [DEFERRED: handler version versus jobs.type_version mismatch]
- Maximum wait for a type with no workers; Phase 1 only alerts. [DEFERRED: maximum wait for a type with no workers]
- How a handler is stopped, how a timeout is enforced, how a worker shuts down, and whether handlers run on the event loop. [ASSUMPTION WK-02] [ASSUMPTION WK-05] [ASSUMPTION WK-08] [ASSUMPTION A-13]
- Which sample handler ships in Phase 1. [ARCH: 18. Open items]
- Defaults for lease length, heartbeat interval, concurrency per pool and the short wait. [ARCH: 15. Configuration]
