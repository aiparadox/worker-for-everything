# job-api

Part 3 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** The public job contract: submit a job, list jobs, read one job with its status, progress and result, read its attempts, and list the job types that exist. It owns the order of checks at submit and hands the whole write to one database transaction. [ARCH: 5. Life of a job] [ARCH: 14. API documentation rules] It runs inside the `api` container. [ARCH: Containers (Docker Compose)]

**Does not do:**
- Run the work. Workers do. [ARCH: 5. Life of a job]
- Publish to RabbitMQ. The transaction writes an outbox row and the relay publishes. [NOTEPAD: D12]
- Authenticate credentials. [accounts-auth#verify-api-key] does. [ARCH: 8. Authentication and authorisation]
- Check files in storage. [file-api#verify-input-files] does. [ARCH: 5. Life of a job]
- Cancel jobs, retry failed jobs by hand, set priorities, delay jobs or send webhooks. [DEFERRED: Phase 2 features: priorities, delayed jobs, cancel, completion webhooks] [DEFERRED: manual retry of a failed job]
- Stream progress. Polling is the baseline. [NOTEPAD: D11]

## 2. Interfaces provided

All five need an API key. Browser logins cannot call the job APIs. [ARCH: 8. Authentication and authorisation] Which scope each endpoint requires is not stated beyond the scope list. [ASSUMPTION A-14]

### 2.1 `submit-job` (`POST /v1/jobs`)

| Item | Detail | Source |
|---|---|---|
| Fields | `type` (R, a registered job type), `payload` (R, JSON object validated against the type's input schema), idempotency key (O, up to 255 characters) | [ARCH: 1. Purpose] [ARCH: 10. Job types and handlers (how new work plugs in)] [DB: jobs.idempotency_key] |
| Where the idempotency key goes (header or body) | Not stated | [ASSUMPTION JA-01] |
| Validation | Known type; payload valid against the input schema; payload within the size cap (default not set); every file in the payload valid | [ARCH: 5. Life of a job] [DB: 8. Write load and size limits] |
| Response | `202` with the job id and an `X-Trace-Id` header; the other body fields are not listed | [ARCH: 12. Observability] [ASSUMPTION A-09] |
| Same key, same request | Returns the existing job. The status code is not stated | [ARCH: 7. Data model] [ASSUMPTION A-09] |
| Same key, different request | A conflict, decided by comparing the stored `request_hash` | [DB: jobs.request_hash] |
| Errors | Unknown type; invalid payload; too large; file problems; idempotency conflict; active-jobs cap reached (429); other rate limits (429) | [ARCH: 5. Life of a job] [ARCH: 9. Rate limiting] [ASSUMPTION JA-03] |
| Limits | Per key and per organisation (Valkey, fail open); active-jobs cap (Postgres, exact) | [ARCH: 9. Rate limiting] |

### 2.2 `get-job` (`GET /v1/jobs/{id}`)

Returns status, progress and result of one job of the caller's organisation. If the result is a file, it includes a short-lived download link. [ARCH: 5. Life of a job] [NOTEPAD: D31] Path parameter `id` is the job id. Other fields (attempt counts, timestamps, error, whether the payload is echoed back) are not listed. [DB: jobs] [ASSUMPTION JA-04] Another organisation's job gives the same answer as a missing one. [ASSUMPTION JA-04]

### 2.3 `list-jobs` (`GET /v1/jobs`)

| Item | Detail | Source |
|---|---|---|
| Query | `status` filter (for example `status=failed`) and keyset pagination on the job id, newest first | [ARCH: 14. API documentation rules] [DB: 9. Performance and tuning plan; Pagination] |
| Other filters, default and maximum page size, cursor format | Not stated | [ASSUMPTION JA-05] |
| Response | A page of jobs. Whether `payload` and `result` are included in list rows is not stated | [ASSUMPTION JA-06] |
| Use | Inspect failures; there is no dead-letter queue | [ARCH: 12. Observability] |

### 2.4 `list-job-attempts` (`GET /v1/jobs/{id}/attempts`)

Returns the tries of one job: attempt number, worker, start, end, outcome (`succeeded`, `retryable_error`, `permanent_error`, `timeout`, `lease_lost`) and error. [ARCH: 14. API documentation rules] [DB: job_attempts.outcome] [DB: job_attempts.attempt_number]

### 2.5 `list-job-types` (`GET /v1/job-types`)

Lists the registered job types and their input schemas. [ARCH: 10. Job types and handlers (how new work plugs in)] The response format (for example JSON Schema) is not stated. [ASSUMPTION JTR-09]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| `accounts-auth` | [accounts-auth#verify-api-key] | Organisation, key id and scopes |
| `rate-limiter` | [rate-limiter#check-request-limit] | Per-key and per-organisation request limits |
| `job-type-registry` | [job-type-registry#get-job-type], [job-type-registry#validate-payload], [job-type-registry#list-registered-types] | Type, schema, `max_attempts`, version, file ids |
| `file-api` | [file-api#verify-input-files], [file-api#create-result-download-link] | Input file checks; result download link |
| `data-access` | [data-access#submit-job-tx], [data-access#get-job], [data-access#list-jobs], [data-access#list-attempts] | All database work |
| `observability` | [observability#trace-context] | Trace id: use the incoming `traceparent`, or generate one |
| `platform` | [platform#startup-config-validation] | Active-jobs cap, payload size cap |

Sources: [ARCH: 5. Life of a job] [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: 12. Observability] [ARCH: 15. Configuration]

## 4. Data

**Reads and writes (through `data-access`):** `jobs` (insert at submit; read), `job_files` (insert at submit), `outbox` (insert one `submit` row at submit), `job_attempts` (read). [DB: 3. Entity overview]

**Who else touches them:** the worker, `maintenance` and the relay, as in [overview.md](overview.md) section 5. [DB: jobs; §5]

## 5. Internal workflow

### 5.1 `submit-job`

1. Authenticate with [accounts-auth#verify-api-key]; check the scope. [ARCH: 8. Authentication and authorisation] [ASSUMPTION A-14]
2. Apply the request limits. The order of this and step 1 is not stated. [ARCH: 9. Rate limiting] [ASSUMPTION A-08]
3. [job-type-registry#get-job-type]; reject an unknown type. [DB: 3. Entity overview]
4. [job-type-registry#validate-payload]; reject an invalid payload; collect the file ids. [ARCH: 10. Job types and handlers (how new work plugs in)]
5. Check the payload size against the cap. [DB: 8. Write load and size limits] [ASSUMPTION JA-12]
6. If an idempotency key was given, compute `request_hash` from the type and the payload. The canonical form of the payload for hashing is not stated. [DB: jobs.request_hash] [ASSUMPTION JA-02]
7. [file-api#verify-input-files], before any transaction or lock. [ARCH: 5. Life of a job]
8. Take the trace id from the incoming `traceparent` or generate one. [ARCH: 12. Observability]
9. [data-access#submit-job-tx] with the organisation, key id, type, version, payload, `max_attempts` from the definition, trace id, file ids, the idempotency key and hash, and the active-jobs cap. [DB: jobs.type_version] [DB: jobs.max_attempts]
10. Map the result: `created` → `202`; `existing` → the existing job; `idempotency-conflict`, `cap-exceeded` and `file-unavailable` → errors. [ARCH: 9. Rate limiting] [ASSUMPTION JA-03]
11. Return the job id with `X-Trace-Id`. [ARCH: 12. Observability]

### 5.2 `get-job`, `list-jobs`, `list-job-attempts`

1. Authenticate and apply limits. [ARCH: 8. Authentication and authorisation] [ARCH: 9. Rate limiting]
2. Call the matching [data-access#get-job], [data-access#list-jobs] or [data-access#list-attempts] scoped by organisation. [DB: 1. Principles]
3. For a result file, ask [file-api#create-result-download-link]. [NOTEPAD: D31]
4. Return the page or the item. [ASSUMPTION JA-04] [ASSUMPTION JA-06]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Unknown type, invalid payload, too large | Rejected; no job | None | [ARCH: 5. Life of a job] |
| File check fails | Rejected; no job; files that were found are already `available` | Possibly `available` files with no job | [ARCH: 5. Life of a job] [ASSUMPTION FA-10] |
| `submit-job-tx` fails before commit | Nothing written; the client gets an error and may retry | None | [DB: jobs; §5 Submit job] |
| Response lost after commit | The job exists and will run, but the client does not know. With an idempotency key a retry returns it; without a key a retry creates a second job | A job the client did not see | [ARCH: 7. Data model] [ASSUMPTION JA-08] |
| Cap reached | Rejected with a rate-limit style answer | None | [ARCH: 9. Rate limiting] |
| Valkey down | Request limits fail open; the cap still works | None | [ARCH: 9. Rate limiting] |
| Database down | Every job endpoint fails | None | [DB: 1. Principles] |
| Repeat of an earlier submit | File checks run again first and can fail before the idempotency check returns the existing job | None | [CONFLICT C-02] |

## 7. Concurrency and idempotency

- Same-organisation submits are serialised by the advisory lock inside the transaction; different organisations do not block each other. [DB: jobs; §6]
- The idempotency key is unique per organisation; a collision returns the existing job. [DB: jobs.idempotency_key] [ARCH: 11. Reliability and delivery]
- Without a key, `submit-job` is not idempotent. [ASSUMPTION JA-08]
- Reads need no coordination. [DB: jobs; §5 List and poll]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Submit path:** one key lookup, a payload validation, file checks (storage calls), then one transaction with the lock, a capped count and three or more inserts. About 50 per second sustained at L-01. [DB: jobs; §6] [ASSUMPTION L-01]
- **Polling:** with no push, clients poll `get-job`. At L-02, 2,000 running jobs polled every 2 seconds is about 1,000 reads per second, each preceded by a key lookup. [NOTEPAD: D11] [ASSUMPTION L-02] [ASSUMPTION JA-09]
- **Listing:** keyset pagination on indexes `(organisation_id, id DESC)` and `(organisation_id, status, id DESC)` keeps page cost flat. [DB: jobs; Indexes]
- **Row size:** `payload` and `result` are jsonb; including them in lists or responses can be large. [DB: jobs.payload] [ASSUMPTION JA-06]
- **Rate limits** per key and per organisation are the only protection against heavy polling. [ARCH: 9. Rate limiting]

## 9. Security

- **Who may call:** API keys only, within their scopes. [ARCH: 8. Authentication and authorisation]
- **Isolation:** every read and write is scoped by the organisation of the key. [ARCH: 8. Authentication and authorisation] [DB: 1. Principles]
- **Input:** all inputs are validated against schemas. [ARCH: 16. Security notes]
- **Job ids** are UUIDv7 and reveal roughly when a job was created. [NOTEPAD: D13]
- **Error text** stored on a job (`jobs.error` message) can come from handler code or libraries, and is returned to the client. Whether it is filtered is not stated. [DB: jobs.error] [ASSUMPTION JA-10]
- **Logs** record ids and sizes, not payload content. [ARCH: 16. Security notes]

## 10. Open questions and deferred items

- Cancel, priorities, delayed jobs, webhooks, manual retry. [DEFERRED: Phase 2 features: priorities, delayed jobs, cancel, completion webhooks] [DEFERRED: manual retry of a failed job]
- Fair scheduling between organisations in one job type's queue. [DEFERRED: fair scheduling between organisations inside one job type's queue]
- Per-organisation limit overrides. [DEFERRED: per-organisation limit overrides]
- Repeated submit order versus idempotency check. [CONFLICT C-02]
- The idempotency key placement, status codes for each outcome, response and list shapes, page size limits, and what a job's error text may contain. [ASSUMPTION JA-01] [ASSUMPTION JA-03] [ASSUMPTION JA-04] [ASSUMPTION JA-05] [ASSUMPTION JA-10]
