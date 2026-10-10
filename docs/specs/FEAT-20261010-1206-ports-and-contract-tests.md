# FEAT-20261010-1206: port interfaces and contract test suites

Status: **approved by the user on 2026-10-10** (all questions in the last section answered yes; recommendations accepted as written). Working branch: `feat-20261010-1206-ports`, from `master` after `FEAT-1205`. Depends on: `FEAT-20261010-1208` (packages; no running service is needed).

## 1. What this builds and why

The "plug" shapes that make parts replaceable (`ARCHITECTURE.md` section 6): interfaces in `qfe/ports/`, an in-memory fake for each, and one **contract test suite** per port. A real adapter (RabbitMQ, SeaweedFS, Valkey) must pass the same suite as the fake. That is what makes "replace RabbitMQ later" safe (`ARCHITECTURE.md` section 13). In this task only the fakes run the suites; the real adapters in `FEAT-1213`, `FEAT-1214` and `FEAT-1219` plug into them later.

## 2. Verified facts and what is not settled

- The methods of the ports come from the part files: `queue-adapter.md` (`declare-queue`, `publish-message`, `consume-queue`, `ack-message`, `nack-requeue`), `storage-adapter.md` (`create-presigned-upload`, `create-presigned-download`, `head-object`, `delete-object`, `read-object`, `write-object`, `ensure-bucket`), `rate-limiter.md` (`check-request-limit` and its limit classes). The catalogue is in `overview.md` section 6.
- `publish-message` has four outcomes by design: `confirmed`, `returned` (not routable), `rejected`, `unknown` (lost confirmation, may be a duplicate). The notepad records that aio-pika needs `on_return_raises=True` to report a returned message; the port hides that detail.
- **Not settled:** the shape of `consume-queue` (the worker gate, prefetch, shutdown) depends on the open questions in `ISS-20261010-1155` (handler execution, delivery settings). The `QueueAdapter` port is written with the consume part as the design describes it today and is marked provisional until the worker spec.
- **Not defined in the design at all:** the `AuthProvider` interface (it is named in `ARCHITECTURE.md` but no part file gives its methods). The repository interfaces are described as a long list of named transactional operations in `data-access.md`.

## 3. Proposal

### 3.1 Scope change to the task (please confirm)

`FEAT-1206` in `TODO.md` also lists `AuthProvider` and the repositories. I propose to **move them** to where they are really designed and tested: the repository interfaces to `FEAT-1211` (data-access, because their meaning is in the SQL transactions and they can only be tested against Postgres), and `AuthProvider` to `FEAT-1218` (accounts and auth). This task then covers `QueueAdapter`, `StorageAdapter`, `RateLimiter`, `Clock` and `IdGenerator`. Defining an interface nobody has used yet usually gets it wrong. If you prefer to keep them here, the cost is rewriting them later.

### 3.2 Ports

All in `qfe/ports/`, written as `typing.Protocol` classes with async methods (no inheritance needed by adapters). Result types are small frozen dataclasses or enums in `qfe/ports/`.

| Port | Methods (from the part files) | Notes |
|---|---|---|
| `QueueAdapter` | `declare_queue(job_type)`, `publish(routing_key, body, headers) -> PublishResult`, `consume(...)` (provisional), `ack(delivery)`, `nack_requeue(delivery)` | `PublishResult` = confirmed, returned, rejected, unknown |
| `StorageAdapter` | `create_presigned_upload(...)`, `create_presigned_download(...)`, `head_object(key)`, `delete_object(key)`, `read_object(key)`, `write_object(key, data)`, `ensure_bucket()` | upload link is a POST policy with a size range (notepad requirement 7) |
| `RateLimiter` | `check(request_class, subject) -> Decision` | classes and fail-open or fail-closed rules from `rate-limiter.md` |
| `Clock` | `now()` | for application times only (token expiry); anything compared in the database uses the database clock (`DATABASE.md` section 2) |
| `IdGenerator` | `new_token()` for random values the application must create itself (lease tokens, token ids, key secrets) | **Primary keys are not made here**: Postgres makes them (D41) |

### 3.3 Fakes and contract suites

- Fakes live in `backend/tests/fakes/`: in-memory queue (with the four publish outcomes, including "no queue declared" giving `returned`), in-memory storage, in-memory rate limiter (also lets tests force the "store is down" state), a settable `Clock`, a deterministic `IdGenerator`.
- Suites live in `backend/tests/contract/<port>/`: a test class that receives the adapter from a fixture. `FEAT-1213` and similar subclass it and supply the real adapter. The suite for `QueueAdapter` must cover "one queue per type", "an unroutable publish is reported" and "an unacked message is delivered again" (`ARCHITECTURE.md` section 13).
- The fakes are not shipped in the application image.

### 3.4 Import rule test

A unit test reads the source with Python's `ast` module and fails if anything under `qfe/domain/` or `qfe/application/` imports from `qfe.adapters`. No new dependency. This enforces the rule in `ARCHITECTURE.md` section 6.

## 4. Tests

The contract suites run against the fakes and pass. The import rule test passes on the skeleton and fails on a deliberately bad import in a test copy (proving it can fail). `mypy` strict passes on the ports.

## 5. Check for the same problem elsewhere

Lateral: every port gets a fake, a suite and a type check, not only the first two. Causal depth: an interface can be wrong because the method is missing, because the failure outcomes are not modelled (the main risk for the queue and storage ports), or because the fake is more forgiving than the real service. The third is why the same suite later runs against the real services, and why the fakes are required to reproduce the failure outcomes, not just the happy path.

## 6. Out of scope

The real adapters (`FEAT-1213`, `FEAT-1214`, `FEAT-1219`), the repositories (`FEAT-1211`), `AuthProvider` (`FEAT-1218`).

## 7. Questions for you

1. Move `AuthProvider` to `FEAT-1218` and the repositories to `FEAT-1211` as in 3.1? If yes, I edit the text of `FEAT-1206` in `TODO.md` to match.
2. `IdGenerator` only makes random tokens, never primary keys (because of D41). OK?
