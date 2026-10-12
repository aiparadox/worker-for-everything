# FEAT-20261010-1212: job type registry

Status: **draft for approval**. Working branch: `feat-20261010-1212-job-types`, from `master`. Depends on: `FEAT-20261010-1210` (merged: the retry policy). Used by: `FEAT-1211` (copies the type name, version and max attempts into a job row), `FEAT-1213` to `FEAT-1217` (queue per type), `FEAT-1220` (submit and `GET /v1/job-types`), `FEAT-1216` (worker).

## 1. What this builds and why

The light, shared list of what the system can run. A **job type definition** says: the name, the version, what the input looks like, what the result looks like, the time limit and the retry policy. The API, relay and worker all import it, so it must stay light: no OCR or AI libraries (`ARCHITECTURE.md` section 6). The heavy code that does the work ("handlers") lives elsewhere and only workers load it.

This task builds: the definition type, the `FileRef` type that marks file ids inside a payload, `PermanentError`, the registry (registered explicitly in one file, nothing discovered by magic), payload validation, and the `echo` job type that every test and example uses.

## 2. What I checked

| Fact | Source |
|---|---|
| Definition fields: name, version, input schema, output schema, timeout, max attempts, retry delays, jitter. The name becomes `jobs.type`, the outbox routing key and the queue name; the version is copied to `jobs.type_version`; `max_attempts` to `jobs.max_attempts` | `job-type-registry.md` 2.1, `DATABASE.md` 4.9 |
| Retry settings are per job type, with defaults: now a `RetryPolicy` (`FEAT-1210`), default from `QFE_DEFAULT_*` | `FEAT-1210` (and its config change) |
| Input schemas mark file fields with a typed `FileRef`; that is how the API finds file ids in a free-form payload and checks, before any transaction, that each file belongs to the organisation and exists | `ARCHITECTURE.md` sections 5 and 10 |
| `PermanentError` fails a job at once with no retries; anything else is retried until `max_attempts` | `ARCHITECTURE.md` section 10 |
| Definitions are registered explicitly in one file; duplicates and malformed definitions should stop startup (the design did not say so: JTR-04); `FileRef` wire form (JTR-06), what `validate-payload` returns on error (JTR-01) and who enforces `timeout` (JTR-08) are open in the design | `job-type-registry.md` section 5 and 10, `findings.md` |
| Pydantic reports validation errors with the **input value** inside each error. A payload may hold sensitive documents' text, so error details must not echo values back (`ARCHITECTURE.md` section 16) | Pydantic behaviour; `ARCHITECTURE.md` section 16 |

## 3. Proposal

All in `qfe/job_types/` (importable by the API and relay without heavy imports).

### 3.1 The definition (`definition.py`)

`JobTypeDefinition`, immutable:

| Field | Rule |
|---|---|
| `name` | lower-case dotted words, for example `echo` or `ocr.extract` (checked by a pattern, 1 to 100 characters). It is also a RabbitMQ queue name and a metric label, so only safe characters |
| `version` | text such as `1`; copied to `jobs.type_version` |
| `input_schema`, `output_schema` | Pydantic models (the input model rejects unknown fields) |
| `timeout_seconds` | positive; a setting of the definition. **Who enforces it is the worker's job** (`FEAT-1216`, question 2 of `ISS-1155`); here it is only stored and shown |
| `retry_policy` | a `RetryPolicy`, or `None` meaning "use the default policy from configuration". `max_attempts_for(default)` returns the effective policy |

### 3.2 `FileRef` (`file_ref.py`)

A field typed `FileRef` is a UUID on the wire (a JSON string). It is a UUID subclass, so the validated payload holds `FileRef` objects, and finding every file id is a plain walk over the validated data (works for a single field, a list, an optional field and nested models). Its JSON schema is `{"type": "string", "format": "uuid", "x-file-ref": true}` so `GET /v1/job-types` can tell clients which fields are files. Whether a file belongs to the organisation and exists is **not** checked here (`FEAT-1221`).

### 3.3 `PermanentError` (`errors.py`)

`PermanentError(Exception)`, with a short message and an optional error code (the code is what clients see; the message may be filtered, `findings.md` F-26).

### 3.4 The registry (`registry.py`)

- `JobTypeRegistry`: `register(definition)`, `get(name)` (raises `UnknownJobType`), `names()`, `definitions()`. Registering a duplicate name raises at once.
- `default_registry()`: **the one file that lists the types**, currently only `echo`. A test fails if a definition exists in the package but is not registered, so nothing is forgotten.
- `validate_payload(name, payload)`: validates a JSON object against the input schema and returns the validated model, the payload as plain JSON, and the list of file ids found. On failure it raises `InvalidPayload` carrying a list of problems, each with the field path (`loc`), a message and an error code, and **never the input value**. The size cap is checked by the caller (the API), as the design says.
- Startup checks stay explicit: `registry.require(names)` raises for any unknown name (the worker uses it for `WORKER_JOB_TYPES`, `*` expands to all names).

### 3.5 The `echo` type

Input: `message` (text, up to 10,000 characters), plus three test controls that exist so the end-to-end flows and the failure paths can be exercised with a real job: `fail_attempts` (fail with a retryable error on the first N tries, default 0), `permanent_error` (fail with `PermanentError`, default false) and `sleep_seconds` (wait that long, up to 3600, default 0; for lease and heartbeat tests). Output: `message` and the attempt number it ran on. Version `1`, default retry policy. **The handler itself and the handler contract (sync or async, the context object) belong to the worker design (`FEAT-1216`, question 2 of `ISS-1155`)**; this task defines only the light definition. I will write the handler together with the worker so that it fits.

### 3.6 Not in this task

`GET /v1/job-types` (`FEAT-1220`), file ownership checks (`FEAT-1221`), the handler contract and handlers (`FEAT-1216`), the real sample handler (`FEAT-1224`), queue declaration (`FEAT-1213`).

## 4. Tests (unit)

- Definition rules: bad names (empty, upper case, spaces, slash, too long), non-positive timeout, unknown input fields rejected.
- Registry: register and get; duplicate refused; unknown type raises; `require` names the missing types; every definition in the package is registered.
- `validate_payload`: a valid echo payload round-trips; file ids are found in a single field, a list, an optional field and a nested model (using test definitions), with duplicates kept once; invalid payloads give paths and messages and **do not contain the submitted value** (a secret-looking string in the payload never appears in the error text); a wrong type, a missing field and an unknown field are all reported; an input model that is not a JSON object is refused.
- `FileRef`: accepts a UUID string, rejects other strings, serialises back to a string, JSON schema carries `x-file-ref`.
- Retry fallback: a type without a policy gets the default; a type with its own policy keeps it.
- **Light import:** a fresh Python process that imports `qfe.job_types` does not import `qfe.handlers`, `qfe.adapters`, `boto3`, `aio_pika`, `sqlalchemy` or `redis` (so the API and relay stay light).
- The echo definition: version, schemas, limits.

## 5. Check for the same problem elsewhere

Lateral: the rule "an error never echoes the input" applies to every place that reports a validation problem: the payload here, and later the request bodies of the accounts and file APIs; the helper that strips values is written once in `qfe/job_types` and `FEAT-1218` and `FEAT-1221` reuse the idea (their specs say how). Causal depth: a bad payload can fail because of the shape, a type, a missing field, an unknown field, or a size; shape, type, missing and unknown are handled here, size by the caller.

## 6. Questions for you

1. The three test controls on `echo` (`fail_attempts`, `permanent_error`, `sleep_seconds`) live in a production type. I recommend it: they make the failure and retry flows testable end to end with no extra code and are harmless. Alternative: a separate `echo.test` type registered only in development. OK with the first?
2. `FileRef` is a UUID string, valid in lists, optional fields and nested models. OK?
3. Unknown fields in an input are **rejected** (strict inputs). OK?
