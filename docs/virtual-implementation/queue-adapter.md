# queue-adapter

Part 9 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** The `QueueAdapter` port and its first implementation on RabbitMQ. It gives the rest of the system one queue per job type, a way to publish a "job is ready" message and learn whether the broker really accepted and routed it, and a way to consume messages, acknowledge them and hand them back. [ARCH: 6. Code structure and the adapter rule] [ARCH: 11. Reliability and delivery] The broker only delivers "this job is ready"; job state always lives in Postgres. [NOTEPAD: D5]

**Does not do:**
- Decide what goes on the queue. [outbox-relay#job-ready-message] defines the message, and the relay decides when to publish. [DB: outbox.body]
- Claim jobs or touch Postgres. [worker#consume-loop] calls [data-access#claim-job]. [ARCH: 5. Life of a job]
- Delay messages. There are no broker delay queues; delays are held in `outbox.run_at`. [ARCH: 11. Reliability and delivery] [NOTEPAD: D22]
- Dead-letter anything. There is no dead-letter queue. [NOTEPAD: D25]
- Decide how many jobs a worker may run at once. That is the worker's concurrency setting. [ARCH: Worker pools and concurrency (D35)]

## 2. Interfaces provided

Contract tests for this port must cover "one queue per type" and "an unroutable publish is reported", and every future adapter must pass the same suite. [ARCH: 13. Testing]

### 2.1 `declare-queue`

| Item | Detail | Source |
|---|---|---|
| Params | `job_type` (R, text) | [ARCH: 11. Reliability and delivery] |
| Effect | Declares a durable queue named after the job type, bound to a direct exchange with the job type as the routing key | [ARCH: 5. Life of a job] [ARCH: 11. Reliability and delivery] |
| Returns | `ok` | [ASSUMPTION QA-01] |
| Repeatable | Yes. Every process that knows a type (api, relay, worker) declares it at startup, idempotently | [ARCH: 11. Reliability and delivery] |
| Exchange name, queue arguments, and whether messages are persistent | Not stated | [ASSUMPTION QA-01] [ASSUMPTION QA-02] |

### 2.2 `publish-message`

| Item | Detail | Source |
|---|---|---|
| Params | `routing_key` (R, the job type), `body` (R), `headers` (R, includes the trace id) | [DB: outbox.routing_key] [DB: outbox.body] [DB: outbox.headers] |
| Behaviour | Publishes with the mandatory flag and publisher confirms. The channel must be opened with `on_return_raises=True` (aio-pika), otherwise a returned message is handed back instead of raising an error | [ARCH: 11. Reliability and delivery] [NOTEPAD: Phase 0 verification results] |
| Returns | `confirmed` only when the broker confirmed the message and did not return it | [DB: outbox.published_at] |
| Returns | `returned` when RabbitMQ could not route it (for example no queue exists for the type). RabbitMQ returns it before it would confirm it | [ARCH: 11. Reliability and delivery] |
| Returns | `rejected` when the broker answers Nack or Reject | [NOTEPAD: Phase 0 verification results] |
| Returns | `unknown` when the confirmation is lost. The message may or may not have been published, and retrying can create a duplicate | [NOTEPAD: Phase 0 verification results] |
| Timeout | The aio-pika call accepts one; its value is not stated | [NOTEPAD: Phase 0 verification results] [ASSUMPTION QA-09] |

### 2.3 `consume-queue`

| Item | Detail | Source |
|---|---|---|
| Params | `job_types` (R, the list from `WORKER_JOB_TYPES`), `gate` (R, a signal telling whether the worker has free concurrency), `on_message` (R) | [ARCH: Worker pools and concurrency (D35)] [ARCH: 11. Reliability and delivery] |
| Behaviour | Consumes only the queues of the listed types, and only while the worker has free concurrency. When the worker is full it cancels its consumers and starts them again when a place is free | [ARCH: 11. Reliability and delivery] |
| Delivery object | Carries the body, the headers and enough to ack or nack it. The exact fields, including a redelivered flag, are not stated | [ASSUMPTION QA-08] |
| Prefetch | Messages already on their way can still arrive after the cancel, so a worker may briefly hold at most one delivered, unclaimed message per queue. That bound needs a prefetch of 1 per consumer, which the sources do not state | [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-03] |

### 2.4 `ack-message` and `nack-requeue`

| Interface | Params | Effect | Source |
|---|---|---|---|
| `ack-message` | the delivery | Tells RabbitMQ to forget the message. Called right after the claim commits, or after a claim is refused | [ARCH: 5. Life of a job] [NOTEPAD: D23] |
| `nack-requeue` | the delivery | Hands the message back so another worker can take it. Used when a delivered message cannot start within a short wait (a tuning value) | [ARCH: 11. Reliability and delivery] |

The sources define no `reject without requeue` use: an unprocessable message is acked, not rejected. [NOTEPAD: D25]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| RabbitMQ 4 | AMQP: exchange, queues, bindings, publish with confirms, consume, cancel, ack, nack | Everything above. aio-pika is the candidate client, not yet pinned or approved. [NOTEPAD: Phase 0 verification results] |
| `platform` | [platform#startup-config-validation] | Broker URL and credentials arrive as required configuration. [ARCH: 15. Configuration] |
| `observability` | [observability#trace-context] | Headers carry the trace id so the worker continues the same trace. The adapter passes the headers through. [ARCH: 12. Observability] [ASSUMPTION QA-11] |

## 4. Data

**Tables:** none read or written. [DB: 7. Data that is not in Postgres]

**Broker objects it owns:** one direct exchange and one durable queue per job type. [ARCH: 11. Reliability and delivery]

**Who else touches them:** RabbitMQ's own Prometheus metrics expose queue depth and consumer counts to the alerts "a queue has messages but no consumers" and "queue depth growing per job type". [ARCH: 12. Observability] [NOTEPAD: D28]

## 5. Internal workflow

### 5.1 `declare-queue`

1. Open a channel and declare the direct exchange (idempotent). [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-01]
2. Declare the durable queue named after the type. [ARCH: 5. Life of a job]
3. Bind it to the exchange with the type as the routing key. [ARCH: 11. Reliability and delivery]

### 5.2 `publish-message`

1. Use a channel with publisher confirms on and `on_return_raises=True`. [NOTEPAD: Phase 0 verification results]
2. Publish with `mandatory=True` (this is the aio-pika default). [NOTEPAD: Phase 0 verification results]
3. If the broker returns the message (no route), report `returned`; the return arrives before any confirm. [ARCH: 11. Reliability and delivery]
4. If the broker nacks, report `rejected`. [NOTEPAD: Phase 0 verification results]
5. If a clean confirm arrives, report `confirmed`. [DB: outbox.published_at]
6. If the connection or channel is lost before an answer, report `unknown`. [NOTEPAD: Phase 0 verification results]

### 5.3 `consume-queue`

1. For each type in `job_types`, start a consumer. [ARCH: Worker pools and concurrency (D35)]
2. When a message arrives, pass the delivery to `on_message`. [ARCH: 5. Life of a job]
3. When the worker reports it is full, cancel all consumers; when a place frees up, start them again. [ARCH: 11. Reliability and delivery]
4. If a delivered message cannot start within the short wait, `nack-requeue` it. [ARCH: 11. Reliability and delivery]
5. With concurrency 1, every running job makes the worker "full". To avoid holding a prefetched message for the whole job, the consumer must be cancelled before the ack of the message that fills the last place. The sources do not state this order. [ARCH: Worker pools and concurrency (D35)] [ASSUMPTION QA-05]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Publish: no queue for the type | `returned`; the relay keeps `published_at` null and records the failure | Outbox row stays due | [ARCH: 11. Reliability and delivery] |
| Publish: broker down or channel lost | `unknown` or an error; the row stays unpublished and is tried again, which can duplicate | Possible duplicate message | [NOTEPAD: Phase 0 verification results] |
| Broker restarts and messages were not persistent | Messages in the queue are lost. The sweep re-queues waiting jobs | Jobs `queued` or `retrying` with no message | [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-02] |
| Ack lost after the claim committed | RabbitMQ redelivers; the claim is refused and the worker acks again | None | [ARCH: 5. Life of a job] |
| Worker dies holding an unacked message | The message is redelivered; if the claim had committed, the claim is refused | None | [ARCH: 5. Life of a job] |
| A delivered message waits more than the consumer timeout (30 minutes by default) | RabbitMQ closes the channel with `PRECONDITION_FAILED` | Unacked messages on that channel are redelivered | [NOTEPAD: Phase 0 verification results] [ARCH: 11. Reliability and delivery] |
| Connection loss at a consumer | Recovery behaviour (reconnect, resume the cancelled consumers) is not described | Worker may stop receiving | [ASSUMPTION QA-04] |
| `declare-queue` finds the queue already exists with different arguments | RabbitMQ refuses the declaration | Process cannot start | [ASSUMPTION QA-06] |

## 7. Concurrency and idempotency

- `declare-queue` can run from any number of processes at once. [ARCH: 11. Reliability and delivery]
- Duplicate messages are expected: the claim refuses a job that is running, finished or not yet due. [ARCH: 11. Reliability and delivery]
- Several workers consume the same queue as competing consumers. A job type's queue is first-in-first-out across all organisations. [ARCH: 11. Reliability and delivery]
- Concurrent publishes: whether the relay publishes one message at a time or several in flight is not stated. [ASSUMPTION QA-07]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Publish rate:** about 50 per second sustained and 200 at the peak at L-01. If each publish waits for its confirm in turn and a confirm takes a few milliseconds, one relay can do several hundred per second. That latency figure is my estimate. [ASSUMPTION QA-07] [ASSUMPTION L-01]
- **Connections and consumers:** at L-02 there are 2,000 jobs running at once. A pool with concurrency 1 needs one worker process per running job, each with its own connection and consumers. That is thousands of connections to the broker. [ARCH: Worker pools and concurrency (D35)] [ASSUMPTION QA-10] [ASSUMPTION L-02]
- **Cancel and restart churn:** at concurrency 1, each job causes a consumer cancel and a restart, so two extra AMQP operations per job. [ARCH: 11. Reliability and delivery] [ASSUMPTION QA-05]
- **Queue count:** one per job type, so about 10 at L-07. [NOTEPAD: D28] [ASSUMPTION L-07]
- **Backlog:** queue depth is the symptom of overload and is alerted on per type. [ARCH: 12. Observability]

## 9. Security

- Only the relay publishes and only workers consume; both use credentials delivered as required configuration. [ARCH: 15. Configuration] Separate broker users and permissions for publishers and consumers are not described. [ASSUMPTION QA-12]
- Messages carry the job id, not the payload, so the broker holds no document content. [DB: outbox.body] [ARCH: 16. Security notes]
- Queues exist only for registered job types, which limits what a caller can address. [ARCH: 11. Reliability and delivery]
- There is no tenant separation inside a queue. [ARCH: 11. Reliability and delivery]

## 10. Open questions and deferred items

- Priorities would use RabbitMQ priority on each queue. A queue's priority argument is fixed when it is declared, so adding it to existing durable queues conflicts with the idempotent startup declaration. [DEFERRED: priorities on the per-type queues] [ASSUMPTION QA-06]
- Fair scheduling between organisations inside a queue. [DEFERRED: fair scheduling between organisations inside one job type's queue]
- Other adapters (Postgres queue, Redis Streams, SQS). [DEFERRED: other queue adapters]
- Maximum wait for a type with no workers; Phase 1 only alerts. [DEFERRED: maximum wait for a type with no workers]
- Whether `consumer_timeout` is set to its default or a larger value. [NOTEPAD: Phase 0 verification results]
- Persistent messages, exchange and queue names, reconnect behaviour and the short wait before a nack. [ASSUMPTION QA-01] [ASSUMPTION QA-02] [ASSUMPTION QA-04] [ASSUMPTION QA-09]
- The aio-pika calls for cancelling and resuming consumers and for prefetch were not read. [NOTEPAD: Phase 0 verification results]
