# outbox-relay

Part 8 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** Reads outbox rows whose time has come and publishes each one to the RabbitMQ queue for its job type, marking a row published only after the broker confirms the message was received and routed. This closes the gap between "job saved in Postgres" and "message on the queue". [ARCH: 5. Life of a job] [NOTEPAD: D12] It is its own container, same image as the API with a different command, so publishing keeps going when the API restarts. [ARCH: Containers (Docker Compose)]

**Does not do:**
- Create outbox rows. The API, the worker and `maintenance` insert them in the same transaction as the status change that needs them. [ARCH: 5. Life of a job] [DB: outbox.reason]
- Decide retries or delays. The delay is already in `outbox.run_at`. [NOTEPAD: D22]
- Fail a job after many failed publishes. Phase 1 only logs, counts and alerts. [ARCH: 11. Reliability and delivery] [DEFERRED: failing a job after N failed publishes]
- Delete published rows. That is a `maintenance` cleanup. [DB: 10. Retention and cleanup; outbox]
- Use `LISTEN/NOTIFY` to wake up; it polls. [DEFERRED: LISTEN/NOTIFY wake-up for the relay]

## 2. Interfaces provided

### 2.1 `job-ready-message`

The message published for one outbox row.

| Part | Content | Required | Source |
|---|---|---|---|
| Routing key | The job type, copied from `outbox.routing_key` | R | [DB: outbox.routing_key] [NOTEPAD: D28] |
| Headers | Copied from `outbox.headers`; include the trace id so the worker continues the same trace | R | [DB: outbox.headers] [ARCH: 12. Observability] |
| Body | Copied from `outbox.body`; carries the job id and not the payload. The exact fields are not stated | R | [DB: outbox.body] [ASSUMPTION RLY-02] |
| Publish flags | Mandatory, with publisher confirms | R | [ARCH: 11. Reliability and delivery] |

A consumer must not assume the message is unique: it can be published twice if the relay crashes after publishing and before saving `published_at`. [DB: outbox; §4.11 rules]

### 2.2 `stuck-outbox-metrics`

The relay counts failed publishes and exposes a "stuck outbox rows" metric that feeds an alert. [ARCH: 12. Observability] What makes a row "stuck" (how many failed attempts, or how long it has been due) is not stated. [ASSUMPTION RLY-07]

### 2.3 Run settings

| Setting | Meaning | Source |
|---|---|---|
| poll interval | How long to wait when no rows are due. The sources say a first run can wait "about a second" | [ARCH: 11. Reliability and delivery] |
| batch size | Rows taken per cycle | [DB: outbox; §4.11] |
| publish timeout | Longest wait for one publish, so row locks are not held for long | [DB: outbox; §4.11 rules] |

Their default values are not set. [ARCH: 15. Configuration] [ASSUMPTION RLY-05]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| `data-access` | [data-access#fetch-due-outbox] | Takes a batch of due, unpublished rows, locked with `SKIP LOCKED` inside an open transaction |
| `data-access` | [data-access#mark-outbox-published] | Sets `published_at` after a clean confirm |
| `data-access` | [data-access#record-publish-failure] | Writes `publish_attempts` and `last_error` for a failed publish |
| `data-access` | [data-access#close-batch] | Commits the batch and releases the locks |
| `queue-adapter` | [queue-adapter#publish-message] | Publishes with confirms and learns `confirmed`, `returned`, `rejected` or `unknown` |
| `queue-adapter` | [queue-adapter#declare-queue] | Declares the queue of every registered type at startup |
| `job-type-registry` | [job-type-registry#list-registered-types] | Gives the types whose queues must exist |
| `observability` | [observability#trace-context] | Keeps the trace id in its logs |
| `platform` | [platform#startup-config-validation] | Database and broker settings, validated at startup |

Sources for the rows above: [DB: 5. How the main operations touch the database; Relay publish] [ARCH: 11. Reliability and delivery] [ARCH: 6. Code structure and the adapter rule]

## 4. Data

**Reads:** `outbox` columns `id`, `job_id`, `routing_key`, `headers`, `body`, `run_at`, `published_at`, `publish_attempts`. [DB: outbox]

**Writes:** `outbox.published_at`, `outbox.publish_attempts`, `outbox.last_error`. [DB: outbox.published_at] [DB: outbox.publish_attempts] [DB: outbox.last_error]

**Who else touches `outbox`:** the API inserts submit rows, the worker inserts retry rows, `maintenance` inserts recovery and sweep rows and deletes published rows, and `maintenance` reads it for the sweep's "no unpublished row" check. [DB: outbox.reason] [DB: 10. Retention and cleanup; outbox] [DB: jobs; §5 Sweep]

## 5. Internal workflow

### 5.1 Startup

1. Validate configuration; stop if anything required is missing. [ARCH: 15. Configuration]
2. Declare the queue for every registered job type. [ARCH: 11. Reliability and delivery]

### 5.2 One cycle

1. Call `fetch-due-outbox(batch_size)`: rows with `published_at IS NULL AND run_at <= now()`, ordered by `run_at, id`, locked with `FOR UPDATE SKIP LOCKED`. [DB: outbox.run_at; §4.11]
2. If the batch is empty, close it and wait for the poll interval. [ARCH: 11. Reliability and delivery] [ASSUMPTION RLY-05]
3. For each row, build the [outbox-relay#job-ready-message] and call `publish-message`. [DB: outbox.body]
4. On `confirmed`, call `mark-outbox-published`. [DB: outbox.published_at]
5. On `returned` or `rejected`, call `record-publish-failure`, leave `published_at` null, and count the failure. [ARCH: 11. Reliability and delivery]
6. On `unknown` (lost confirmation) the row must not be marked published, but whether it is recorded as a failure is not stated. [NOTEPAD: Phase 0 verification results] [ASSUMPTION RLY-01]
7. Call `close-batch` to commit and release the locks. [DB: 5. How the main operations touch the database; Relay publish]
8. If the batch was full, start the next cycle at once. [ASSUMPTION RLY-05]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Postgres down | The relay cannot fetch; nothing is published and nothing is lost | Rows wait | [DB: 1. Principles] |
| Broker down | Every publish fails. With a timeout per publish, one batch can keep a transaction and row locks open for batch size times the timeout | Locks held, rows unpublished | [DB: outbox; §4.11 rules] [ASSUMPTION RLY-04] |
| Unroutable message (`returned`) | Failure recorded, row stays due and is selected again next cycle | `publish_attempts` grows | [ARCH: 11. Reliability and delivery] |
| Row that fails every time | It is selected first on every cycle, because the order is `run_at, id`. If such rows fill the batch, no other row is published | All publishing stalls | [DB: outbox; §4.11] [ASSUMPTION RLY-03] |
| Crash after publishing, before `mark-outbox-published` is committed | The transaction rolls back, so every row of that batch that was already published is published again | Duplicate messages, harmless because the claim refuses them | [DB: outbox; §4.11 rules] [ARCH: 11. Reliability and delivery] |
| `record-publish-failure` rolled back with the batch | The failure count is lost | `publish_attempts` under-counted | [ASSUMPTION DA-15] |
| Relay container stops | No job starts; jobs already queued keep their rows. The API keeps accepting submits | Growing backlog of due rows | [ARCH: Containers (Docker Compose)] [ASSUMPTION RLY-08] |
| Row fails "many times" | Logged, counted and alerted on; the job is not failed automatically | Row retried indefinitely | [ARCH: 11. Reliability and delivery] [DB: outbox; §4.11 rules] |

## 7. Concurrency and idempotency

- Several relays may run; `SKIP LOCKED` keeps them off each other's rows. [DB: outbox; §4.11] [ARCH: Containers (Docker Compose)]
- A row is never processed by two relays at the same time, but after a crash it can be published twice. The design relies on the claim to refuse duplicates. [DB: outbox; §4.11 rules] [ARCH: 11. Reliability and delivery]
- Publish order does not follow creation order, because ids are made at insert and not at commit. Nothing may depend on order. [DB: outbox; §4.11 rules]
- A message that arrives before `jobs.run_at` is refused at the claim and acked. The relay and the claim use the same value on the database clock, so a published message is never refused as too early. [DB: 5. How the main operations touch the database] [NOTEPAD: D24]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Volume:** about 50 rows per second sustained and 200 at the peak at L-01, plus a row for every retry, recovery and sweep. [ASSUMPTION L-01] [DB: outbox.reason]
- **Capacity of one relay** depends on how fast each publish is confirmed; the sources do not say whether publishes are sent one at a time or many in flight. [ASSUMPTION QA-07]
- **Latency added to a first run:** up to the poll interval, about a second. [ARCH: 11. Reliability and delivery] [ASSUMPTION L-06]
- **Query:** the partial index on `(run_at, id) WHERE published_at IS NULL` stays small because published rows leave it. [DB: outbox; §4.11]
- **Long transactions:** the batch transaction is open while the relay waits on the broker, which holds row locks and delays vacuum. [DB: outbox; §4.11 rules] [ASSUMPTION RLY-04]
- **Table churn:** about 50 inserts, updates and later deletes per second. Autovacuum thresholds are lowered for `outbox`. [DB: 9. Performance and tuning plan]
- **Single point of failure:** if every relay is down, no job starts. "Small number of instances" is the stated scaling. [ARCH: Containers (Docker Compose)]

## 9. Security

- No external callers; the relay is a background process. [ARCH: Containers (Docker Compose)]
- It uses the `qfe_app` database role and broker credentials, both required configuration. [DB: 9. Performance and tuning plan] [ARCH: 15. Configuration]
- It handles job ids and routing keys only, never payloads. [DB: outbox.body]
- Logs carry the trace id and job id, not content. [ARCH: 12. Observability] [ARCH: 16. Security notes]

## 10. Open questions and deferred items

- Failing a job after N failed publishes. [DEFERRED: failing a job after N failed publishes]
- `LISTEN/NOTIFY` wake-up cannot go through a transaction-pooled connection. [DEFERRED: LISTEN/NOTIFY wake-up for the relay] [NOTEPAD: Phase 0 verification results]
- How a row that fails again and again is kept from blocking other rows, and how it is ever cleared. [ASSUMPTION RLY-03]
- Defaults for poll interval, batch size, publish timeout, and the "stuck row" threshold. [ASSUMPTION RLY-05] [ASSUMPTION RLY-07]
- How the relay reports readiness and how it stops (finish the current batch or drop it). [ASSUMPTION RLY-08] [ASSUMPTION RLY-09]
- Who sees the `unknown` publish outcome and what is recorded. [ASSUMPTION RLY-01]
