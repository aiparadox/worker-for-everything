# file-api

Part 4 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** The file side of the public API: it hands out upload links, looks files up, checks the input files of a job before the job is submitted, and builds the short-lived download link for a result file. Clients upload straight to storage and the job carries file ids, not bytes. [NOTEPAD: D31] [NOTEPAD: D6] It runs inside the `api` container. [ARCH: Containers (Docker Compose)]

**Does not do:**
- Store bytes or sign links itself. [storage-adapter#create-presigned-upload] and [storage-adapter#head-object] do. [ARCH: 6. Code structure and the adapter rule]
- Write the `files` rows itself; [data-access#create-file-row] and [data-access#mark-files-available] do. [DB: 1. Principles]
- Create result files. Who records a `kind = result` row is not stated. [ASSUMPTION A-11]
- List files, delete files or change them. The only file endpoints named are create-a-link and get-one. [ARCH: 14. API documentation rules]
- Scan uploads. [DEFERRED: virus or content scanning of uploads]
- Accept large files in several parts. [DEFERRED: multipart upload for very large files]
- Remove old files. That is `maintenance`, and files used by jobs have no removal chore. [DB: 10. Retention and cleanup] [CONFLICT C-05]

## 2. Interfaces provided

### 2.1 `create-upload-link` (`POST /v1/files`)

| Item | Detail | Source |
|---|---|---|
| Caller | An API key. Which scope it needs is not stated; the scope list has `files:write` | [ARCH: 14. API documentation rules] [ARCH: 8. Authentication and authorisation] [ASSUMPTION A-14] |
| Fields | `file name` (R, up to 255 characters), `size` (R, bytes), `content type` (R) | [NOTEPAD: D31] [DB: files.display_name] [DB: files.size_bytes] [DB: files.content_type] |
| Validation | `size` must not exceed the file size cap; the cap is a tuning value with no default. Allowed content types and file name rules are not stated | [NOTEPAD: D31] [ARCH: 15. Configuration] [ASSUMPTION FA-08] |
| Response | `file_id` and an upload URL. A presigned POST policy also needs form fields; the decision names only a "presigned upload URL" | [NOTEPAD: D31] [NOTEPAD: Phase 0 verification results] [CONFLICT C-04] |
| Effect | A `files` row with `status = pending`, `kind = input`, a server-generated `storage_key` namespaced by organisation, and an `expires_at` | [DB: files.status] [DB: files.storage_key] [DB: files.expires_at] [ARCH: 16. Security notes] |
| Errors | Invalid input; size over the cap; rate limited (429) | [ARCH: 9. Rate limiting] [ASSUMPTION FA-03] |
| Limit | Per key and per organisation, both fail open when Redis is down | [ARCH: 9. Rate limiting] |

### 2.2 `get-file` (`GET /v1/files/{id}`)

| Item | Detail | Source |
|---|---|---|
| Caller | An API key with scope `files:read` | [ARCH: 14. API documentation rules] |
| Path parameter | `id`, the file id | [ARCH: 14. API documentation rules] |
| Response | The file's status and a short-lived download link; the other fields are not listed | [ARCH: 14. API documentation rules] [ASSUMPTION FA-04] |
| Errors | Not found, including a file of another organisation | [DB: 1. Principles] [ASSUMPTION FA-07] |

A file stays `pending` until some job submit checks it, so `status` cannot tell a client that its upload worked. [DB: files.status] [ASSUMPTION FA-04]

### 2.3 `verify-input-files` (internal, called by `job-api`)

| Item | Detail | Source |
|---|---|---|
| Input | `organisation_id`, the list of file ids found in the payload | [ARCH: 5. Life of a job] |
| Behaviour | For each file: it exists and belongs to the organisation, and [storage-adapter#head-object] finds the object. Found files are marked `available`. This happens before any transaction or lock | [ARCH: 5. Life of a job] [NOTEPAD: D36] |
| Returns | `ok`, or a list of problems per file id | [ASSUMPTION FA-07] |
| Size rule | The real size from the check "must match the declared limit"; whether that means the declared size or the size cap is not stated | [DB: files.size_bytes] [ASSUMPTION FA-03] |

### 2.4 `create-result-download-link` (internal, called by `job-api`)

Given an organisation and a result file id, returns a short-lived download link. [NOTEPAD: D31] [ARCH: Containers (Docker Compose)] The sources say `GET /v1/jobs/{id}` returns the link and do not name this step. [ASSUMPTION FA-11]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| `data-access` | [data-access#create-file-row], [data-access#get-file-row], [data-access#mark-files-available] | File records |
| `storage-adapter` | [storage-adapter#create-presigned-upload], [storage-adapter#head-object], [storage-adapter#create-presigned-download] | Links and the existence check |
| `accounts-auth` | [accounts-auth#verify-api-key] | Who is calling and with which scopes |
| `rate-limiter` | [rate-limiter#check-request-limit] | Request limits |
| `platform` | [platform#startup-config-validation] | File size cap, link lifetime, pending-file expiry, public storage URL |

Sources: [NOTEPAD: D31] [ARCH: 5. Life of a job] [ARCH: 15. Configuration]

## 4. Data

**Reads and writes:** `files` (insert pending, mark available, read). [DB: files] It reads `job_files` only indirectly through [data-access#submit-job-tx], which writes it. [DB: job_files]

**Who else touches `files`:** `maintenance` deletes pending rows past `expires_at`; a worker may write a result row; `job-api` follows `jobs.result_file_id`. [DB: 10. Retention and cleanup; files] [DB: jobs.result_file_id] [ASSUMPTION A-11]

## 5. Internal workflow

### 5.1 `create-upload-link`

1. Authenticate the key and check the limits. [ARCH: 8. Authentication and authorisation] [ARCH: 9. Rate limiting]
2. Validate name, size and content type. [ASSUMPTION FA-08]
3. Generate the `storage_key`, namespaced by organisation. Its format is not stated. [ARCH: 16. Security notes] [ASSUMPTION FA-01]
4. [data-access#create-file-row] with `status = pending` and `expires_at`. [DB: files.expires_at] The pending expiry and its relation to the link lifetime are not stated. [ASSUMPTION FA-02]
5. [storage-adapter#create-presigned-upload]; return `file_id` and the link. [NOTEPAD: D31]

### 5.2 `verify-input-files`

1. For each id, [data-access#get-file-row] scoped by organisation; if absent, record a problem. [DB: files.organisation_id]
2. [storage-adapter#head-object] for each file, including files already `available`. [ARCH: 5. Life of a job] [ASSUMPTION FA-12]
3. Compare the real size with the rule above. [DB: files.size_bytes]
4. [data-access#mark-files-available] for the files that passed. [DB: files.status]
5. Return `ok` or the problems. Later, inside the submit transaction, [data-access#submit-job-tx] re-reads the rows and locks them. [NOTEPAD: D36]

### 5.3 `get-file`

1. Authenticate with scope `files:read`. [ARCH: 14. API documentation rules]
2. [data-access#get-file-row] scoped by organisation. [DB: 1. Principles]
3. If available, [storage-adapter#create-presigned-download] and return it. [NOTEPAD: D31]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Storage down during a HEAD | The submit cannot be checked and fails before any transaction | No job | [ARCH: 5. Life of a job] |
| `create-file-row` succeeds, link signing fails | The client gets an error; the pending row expires and is purged | Pending row | [DB: 10. Retention and cleanup; files] |
| Client never uploads | The pending row expires and is purged with its (absent) object | Pending row until expiry | [DB: files.expires_at] |
| File marked `available`, then the submit fails (cap, duplicate key, another file bad) | The file stays `available` with no job; pending purge does not match it, and no other chore removes it | Unused `available` file | [DB: 10. Retention and cleanup; files] [ASSUMPTION FA-10] |
| File deleted from storage between the check and a worker's read | The handler fails that job with a permanent error | Failed job | [NOTEPAD: D36] |
| HEAD finds an object larger than allowed | The submit is rejected | File stays as it was | [DB: files.size_bytes] [ASSUMPTION FA-03] |
| A repeated submit (same idempotency key) | The file checks run again before the idempotency check, so storage work is repeated and a purged file can make the repeat fail | None | [ARCH: 5. Life of a job] [ARCH: 7. Data model] [CONFLICT C-02] |

## 7. Concurrency and idempotency

- Two submits using the same file both run the check and both mark it `available`; marking is repeatable. [ASSUMPTION DA-17]
- A file may be linked to several jobs, because `job_files` is keyed by job and file. [DB: job_files]
- The file rows are locked in the submit transaction so cleanup cannot remove them between the check and the insert. [DB: job_files] [NOTEPAD: D36]
- Creating several upload links is always allowed; each is a new row. [DB: files]
- An upload link remains valid after the file was marked `available`, so the bytes could change after the check. [ASSUMPTION SA-05]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **HEAD calls:** one per file per submit, before the transaction. With 3 files at 200 ms and no parallelism, a submit takes about 0.6 seconds before it starts its transaction. [NOTEPAD: D36] [ASSUMPTION SA-07]
- **Amplification:** nothing limits how many `FileRef` values a payload may hold apart from the payload size cap, and each one costs a storage call. [DB: 8. Write load and size limits] [ASSUMPTION FA-05]
- **At 200 submits per second peak** and 3 files each, about 120 HEAD calls are in flight at once if each takes 200 ms. [ASSUMPTION L-01] [ASSUMPTION SA-07]
- **Rows:** one `files` row per upload link. Abandoned links add rows until purged. [DB: files]
- **Storage volume** per organisation is not limited by any rule described: rate limits count requests, not bytes. [ARCH: 9. Rate limiting] [ASSUMPTION FA-09]
- `get-file` costs one organisation-scoped read plus local signing. [DB: files.organisation_id] [NOTEPAD: Phase 0 verification results]

## 9. Security

- **Who may call:** API keys with the right scope; the internal functions are called only inside the API. [ARCH: 8. Authentication and authorisation] [ASSUMPTION A-14]
- **Isolation:** file lookups are scoped by organisation and the storage key is namespaced by organisation. [DB: files.organisation_id] [ARCH: 16. Security notes]
- **Keys:** the storage key is generated by the server, never accepted from a client. [DB: files.storage_key]
- **Existence leaks:** whether a request for another organisation's file gets the same answer as for a missing one is not stated. [ASSUMPTION FA-07]
- **Links:** short-lived, download links never stored. [NOTEPAD: D31] [DB: files]
- **Content:** no scanning of uploads, and no allow-list of content types is described. [ARCH: 16. Security notes] [ASSUMPTION FA-08]

## 10. Open questions and deferred items

- Upload method and response shape: plain presigned URL or presigned POST policy. [CONFLICT C-04]
- Cleanup of files that jobs used, and of `available` files no job ever used. [CONFLICT C-05] [ASSUMPTION FA-10]
- Repeated submits and the order of file checks versus the idempotency check. [CONFLICT C-02]
- Multipart upload and virus scanning. [DEFERRED: multipart upload for very large files] [DEFERRED: virus or content scanning of uploads]
- Limits on files per payload and on storage per organisation. [ASSUMPTION FA-05] [ASSUMPTION FA-09]
- Storage key format, pending expiry and link lifetime defaults, the exact size rule, error shapes. [ASSUMPTION FA-01] [ASSUMPTION FA-02] [ASSUMPTION FA-03]
- Which part creates result files and their rows. [ASSUMPTION A-11]
