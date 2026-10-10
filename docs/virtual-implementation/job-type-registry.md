# job-type-registry

Part 6 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** Holds the light definition of every job type the system can run: name, version, input and output schemas, and retry settings. The API, the relay and the worker all import it, so it must not pull in heavy libraries such as OCR or AI code. [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: 6. Code structure and the adapter rule] It also owns the function that turns a failed attempt into a retry delay. [ARCH: 10. Job types and handlers (how new work plugs in)]

**Does not do:**
- Run any work. Handler code lives in `handlers/` and is loaded only by workers. [ARCH: 6. Code structure and the adapter rule]
- Check that a file belongs to the organisation or exists. That is [file-api#verify-input-files]. [ARCH: 5. Life of a job]
- Store anything. Job types are not a database table; `jobs.type` is a plain string. [DB: 3. Entity overview] [DB: jobs.type]
- Declare queues or consume them. That is [queue-adapter#declare-queue]. [ARCH: 11. Reliability and delivery]

## 2. Interfaces provided

### 2.1 `job-type-definition` (the shape every definition has)

| Field | Type | Required | Rule | Source |
|---|---|---|---|---|
| `name` | text, for example `ocr.extract` | R | Unique across the registry; becomes `jobs.type`, the outbox `routing_key` and the queue name | [ARCH: 10. Job types and handlers (how new work plugs in)] [DB: jobs.type] [DB: outbox.routing_key] [NOTEPAD: D28] |
| `version` | text | R | Copied to `jobs.type_version` at submit | [DB: jobs.type_version] |
| `input_schema` | Pydantic model | R | Validates the payload at submit. File fields are typed `FileRef` | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| `output_schema` | Pydantic model | R | Describes the result | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| `timeout` | duration | R | A setting of the definition. What enforces it is not stated | [ARCH: 10. Job types and handlers (how new work plugs in)] [ASSUMPTION JTR-08] |
| `max_attempts` | integer, at least 1 | R | Copied to `jobs.max_attempts` at submit; counts the first run plus the retries | [DB: jobs.max_attempts] |
| `retry_delays` | list of durations | R | Base delays before jitter. The planned default is about 10 seconds, 2 minutes and 10 minutes, with `max_attempts` 4, to be confirmed | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| `jitter` | fraction | O | About ±20% in the plan | [ARCH: 10. Job types and handlers (how new work plugs in)] |

Definitions are registered explicitly in one file, not discovered automatically. [ARCH: 10. Job types and handlers (how new work plugs in)]

### 2.2 `file-ref` (type used inside input schemas)

A field typed `FileRef` holds a file id. It is how the API finds file ids inside a free-form payload. [ARCH: 10. Job types and handlers (how new work plugs in)] Its wire form (a string uuid, whether lists and nested objects may hold them, whether optional ones are allowed) is not stated. [ASSUMPTION JTR-06]

### 2.3 `permanent-error` (exception type)

Raised by a handler for bad input, an unsupported file and similar. It fails the job at once with no retries. Any other exception, including timeouts, is retried until `max_attempts`. [ARCH: 10. Job types and handlers (how new work plugs in)]

### 2.4 `handler-signature` (contract a handler must satisfy)

One method, `handle(context, payload)`. The `context` is built by [worker#handler-context]. Handlers must be safe to run twice for the same job. [ARCH: 10. Job types and handlers (how new work plugs in)] Nothing says whether `handle` is synchronous or asynchronous, or who validates the returned result against `output_schema`. [ASSUMPTION A-13] [ASSUMPTION JTR-07]

### 2.5 Functions

| Interface | Params | Returns | Rule | Source |
|---|---|---|---|---|
| `get-job-type` | `name` (R) | the definition or `unknown-type` | The API rejects types that are not registered | [DB: 3. Entity overview] |
| `list-registered-types` | none | all definitions | Feeds `GET /v1/job-types`, the worker's `WORKER_JOB_TYPES` check, and queue declaration at startup | [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: 11. Reliability and delivery] |
| `validate-payload` | `type` (R), `payload` (R, JSON object) | the validated payload and the list of `FileRef` ids found, or `invalid(errors)` | Validates against `input_schema` and collects the file ids so the caller can check them. The shape of `errors` and the HTTP status are not stated | [ARCH: 5. Life of a job] [ARCH: 10. Job types and handlers (how new work plugs in)] [ASSUMPTION JTR-01] |
| `next-retry-delay` | `type` (R), `attempt_number` (R, the number of the attempt that just failed) | a duration with jitter, or `no-more-retries` | A duration, never a timestamp; SQL adds it to the database clock. Used by the worker for retries and by `maintenance` for lease recovery | [ARCH: 10. Job types and handlers (how new work plugs in)] [NOTEPAD: D24] |

## 3. Interfaces consumed

None from other parts. It reads only the registration file and, for tests, the `Clock` port. [ARCH: 10. Job types and handlers (how new work plugs in)] [NOTEPAD: D24]

## 4. Data

**Reads and writes:** no tables. [DB: 3. Entity overview]

**Copied into rows by callers:** `version` → `jobs.type_version`; `max_attempts` → `jobs.max_attempts`; `name` → `jobs.type`. [DB: jobs.type_version] [DB: jobs.max_attempts] [DB: jobs.type]

**Not copied:** `retry_delays` and `jitter`. Only `max_attempts` and the version are stored on the job, so a retry always uses the settings of whichever process computes the delay. [DB: jobs.max_attempts] [ASSUMPTION JTR-05]

## 5. Internal workflow

### 5.1 Startup

1. The registration file builds the set of definitions in memory. [ARCH: 10. Job types and handlers (how new work plugs in)]
2. Duplicate names or malformed definitions should stop startup, but the sources do not say so. [ASSUMPTION JTR-04]
3. A worker compares `WORKER_JOB_TYPES` with the registry, and fails to start if a listed type does not exist. [ARCH: Worker pools and concurrency (D35)]
4. Each process that knows a type declares its queue through [queue-adapter#declare-queue]. [ARCH: 11. Reliability and delivery]

### 5.2 `validate-payload`

1. Look up the definition; if unknown, return `unknown-type`. [DB: 3. Entity overview]
2. Validate the payload against `input_schema`. [ARCH: 10. Job types and handlers (how new work plugs in)]
3. Walk the validated model and collect every `FileRef` value. [ARCH: 10. Job types and handlers (how new work plugs in)] [ASSUMPTION JTR-06]
4. Return the validated payload and the file ids. The size cap on the payload is checked by the caller. [DB: 8. Write load and size limits] [ASSUMPTION JTR-01]

### 5.3 `next-retry-delay`

1. If `attempt_number >= max_attempts`, return `no-more-retries`. [DB: jobs.max_attempts]
2. Pick the base delay for this attempt number from `retry_delays`. With 3 retries and 3 delays, attempt 1 gets about 10 seconds, attempt 2 about 2 minutes, attempt 3 about 10 minutes. [ARCH: 10. Job types and handlers (how new work plugs in)] What happens when fewer delays than retries are configured is not stated. [ASSUMPTION JTR-02]
3. Apply random jitter of about ±20% and return a duration. [ARCH: 10. Job types and handlers (how new work plugs in)] The random source and the distribution are not stated, and the ports list has `Clock` and `IdGenerator` but no random source. [ARCH: 6. Code structure and the adapter rule] [ASSUMPTION JTR-03]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Unknown type at submit | The API rejects the request; no job is created | None | [DB: 3. Entity overview] |
| Payload fails validation | Rejected at submit "with a clear error"; no job is created | None | [ARCH: 5. Life of a job] |
| Handler raises `permanent-error` | The job fails at once | `failed` | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| Handler raises anything else | Retried until `max_attempts` | `retrying`, then `failed` | [ARCH: 10. Job types and handlers (how new work plugs in)] |
| A definition exists in the API image but no handler exists in the worker image (rolling deploy) | The message waits in the type's queue until a worker for that type starts | Job `queued` | [ARCH: 11. Reliability and delivery] |
| A worker has a handler for a different version than `jobs.type_version` | Nothing detects it | Job runs with the wrong schema | [DEFERRED: handler version versus jobs.type_version mismatch] |
| Removing a type | Its queue is left behind | Orphan queue | [NOTEPAD: D28] |

## 7. Concurrency and idempotency

- The registry is built once at startup and only read afterwards, so concurrent readers need no coordination. [ASSUMPTION JTR-04]
- `validate-payload` and `next-retry-delay` keep no state; the same input can be repeated freely, except that jitter makes `next-retry-delay` return different values each call. [ARCH: 10. Job types and handlers (how new work plugs in)]
- Handlers must be idempotent because delivery is at-least-once. [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: 11. Reliability and delivery]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- `validate-payload` runs once per submit, so about 50 per second at L-01 and 200 at the peak, in the API process. Cost grows with payload size, and the payload cap's default is not set. [DB: 8. Write load and size limits] [ASSUMPTION L-01]
- `next-retry-delay` runs once per failed attempt and once per recovered job, which is negligible next to the database writes it feeds. [DB: jobs; §5 Retry]
- `list-registered-types` may be called on every `GET /v1/job-types`. Whether the schemas are rendered once or per request is not stated. [ASSUMPTION JTR-09]
- Pydantic validation of very large payloads is CPU-bound and runs in the API process. [ASSUMPTION JTR-10]

## 9. Security

- Validation is the first line of defence for payload content: all inputs are validated against schemas. [ARCH: 16. Security notes]
- `FileRef` ids are only syntax at this point. Ownership is enforced later by [file-api#verify-input-files] and again inside [data-access#submit-job-tx]. [ARCH: 5. Life of a job] [DB: job_files; §4.8]
- `GET /v1/job-types` exposes input schemas. Which credential kind and scope may call it is not stated. [ARCH: 10. Job types and handlers (how new work plugs in)] [ASSUMPTION A-14]
- Payloads and results may hold sensitive documents, so logs record ids and sizes, not content. [ARCH: 16. Security notes]

## 10. Open questions and deferred items

- Handler version versus `jobs.type_version` mismatch. [DEFERRED: handler version versus jobs.type_version mismatch]
- Which real sample handler ships in Phase 1 (small, uses files and progress). [ARCH: 18. Open items]
- Default values for retry delays, max attempts and timeouts are "to be confirmed". [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: 15. Configuration]
- Who enforces `timeout`, and whether results are validated against `output_schema`. [ASSUMPTION JTR-07] [ASSUMPTION JTR-08]
- Orphan queues after a type is removed need a cleanup policy. [NOTEPAD: D28]
