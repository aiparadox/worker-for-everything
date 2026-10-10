# FEAT-20261010-1209: SeaweedFS end-to-end checks from outside Docker

Status: **approved by the user on 2026-10-10** (all questions in the last section answered yes; recommendations accepted as written). Working branch: `feat-20261010-1209-seaweedfs-checks`, from `master` after `FEAT-1207`. Depends on: `FEAT-20261010-1202` (the `storage` service), `FEAT-20261010-1207` (test harness), `FEAT-20261010-1208` (boto3).

## 1. What this builds and why

The design leans on five SeaweedFS behaviours that so far are known only from documentation and source code, not from running it: presigned uploads with a size limit, links that work from outside Docker, HEAD checks, download links, and expiry of old files. If one is wrong, the file API (`FEAT-1221`) and the storage adapter (`FEAT-1214`) would be built on a false assumption (finding F-08 and the upload design depend on it). This task turns each into a test that passes or fails.

## 2. What is known and what is not (from the notepad, "Phase 0 verification results")

| Claim | Basis today |
|---|---|
| Presigned URLs (SigV4), HeadObject, PostObject, multipart and bucket lifecycle get and put are supported | SeaweedFS wiki, read |
| POST policy `content-length-range` is enforced | upstream source `s3api_object_handlers_postpolicy.go`: it returns EntityTooSmall or EntityTooLarge. **Not run.** Whether the check happens before or after the body is read is **not known** |
| Presigned links are signed for a host name and fail through another; `-s3.externalUrl` fixes that | wiki. **Not run** |
| Lifecycle transition rules are not supported; expiry rules are | wiki says "transition rules not supported". **Whether an expiry rule actually deletes objects is not known** |

## 3. Proposal

Integration tests in `backend/tests/integration/seaweedfs/`, run with boto3 from the host against the `storage` service of the test profile, so the requests really come from outside Docker. They stay in the suite afterwards as regression tests for the adapter.

| # | Check | Pass means |
|---|---|---|
| 1 | Presigned POST with `content-length-range` 1 byte to 1 MiB, uploading a 100 KiB file | upload accepted, object exists with the right size |
| 2 | Same policy, uploading a 5 MiB file | rejected with the size error, and **no object is created**. Also measure whether the server stops reading early (bytes sent before the rejection), and record it |
| 3 | Same policy, uploading 0 bytes | rejected (the lower bound works) |
| 4 | Link signed for the public URL, used from the host | works. Then the same link signed for the Docker-internal host name | fails, which proves why the public URL setting is required |
| 5 | HEAD on an uploaded object | returns size and content type; HEAD on a missing key returns 404 |
| 6 | Presigned GET (download link) | returns the same bytes; an expired link is refused |
| 7 | Object key with the organisation prefix and with unusual characters (spaces, unicode) | the key round-trips unchanged |
| 8 | Lifecycle expiry: put a rule, read it back; then show whether it deletes | The rule is accepted and returned. Deleting needs time: if SeaweedFS offers no way to shorten the unit below one day, the test only proves the rule is stored, and **the result is recorded as "expiry not verified"**, with the reason |
| 9 | Delete object, then HEAD | 404 |
| 10 | Calls made through `asyncio.to_thread` (D47) from several tasks at once | no error with 20 parallel HEAD calls |

## 4. What the task delivers

- The test files above, passing, except check 8 which may be only partly provable.
- A short result section added to the notepad (what each check showed, including the size-limit timing in check 2 and the exact SeaweedFS image tag and command line used).
- If any check fails, the finding is logged and the design is corrected **before** `FEAT-1214` and `FEAT-1221` are specified: for example, if the size limit is not enforced, the second line of defence (the post-upload size check with delete) becomes the only one.

## 5. Check for the same problem elsewhere

Lateral: the same "documented but never run" gap exists for RabbitMQ settings (`consumer_timeout`, `on_return_raises`) and for the Grafana stack; those are covered in `FEAT-1205` and `FEAT-1213`, not here, and are listed so they are not forgotten. Causal depth: "upload works from my laptop but not from a client" has at least three causes — the signed host (check 4), the size policy (checks 1 to 3) and clock skew between signer and server (a presigned link carries a time; the test uses a link with a short life to see the tolerance).

## 6. Out of scope

The adapter itself (`FEAT-1214`), the upload endpoints (`FEAT-1221`), multipart upload, virus scanning.

## 7. Questions for you

None needed. The task depends only on the Compose stack working.
