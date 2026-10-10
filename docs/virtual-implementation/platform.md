# platform

Part 14 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** How the whole system is started and configured: the Docker Compose stack, startup checks that fail loudly on missing required settings, the one-shot migration job, and the database roles. [ARCH: 2. Goals and non-goals] [ARCH: 15. Configuration] [DB: 12. Migrations and change process] The stack must run from one `docker compose up`. [ARCH: 2. Goals and non-goals]

**Does not do:**
- Business behaviour of any service. [ARCH: 15. Configuration]
- Production deployment beyond the Compose file. A target such as Kubernetes, a CI tool, backups and secret storage are not discussed. [ARCH: 17. Roadmap] [ASSUMPTION PLT-02] [ASSUMPTION PLT-09] [ASSUMPTION PLT-10]
- Run PgBouncer: it is not needed in the first version. [NOTEPAD: Phase 0 verification results]
- Send email: no mail container exists in Phase 1. [DEFERRED: email verification and the email sender]

## 2. Interfaces provided

### 2.1 `compose-topology`

| Service | Role | Source |
|---|---|---|
| `api`, `worker` (one or more pools), `relay`, `maintenance`, `frontend` | Application containers; `api`, `worker`, `relay` and `maintenance` use the same image with different commands | [ARCH: Containers (Docker Compose)] |
| `postgres` (version 18) | System of record | [ARCH: Containers (Docker Compose)] [NOTEPAD: D13] |
| `rabbitmq` | One queue per job type | [ARCH: Containers (Docker Compose)] [NOTEPAD: D28] |
| `redis` | Rate limit counters only | [ARCH: Containers (Docker Compose)] |
| `storage` (SeaweedFS) | Documents, scans, results | [ARCH: Containers (Docker Compose)] [NOTEPAD: D20] |
| `otel-collector`, `tempo`, `loki`, `prometheus`, `grafana` | Observability; can be switched off for light local work | [ARCH: Containers (Docker Compose)] [ARCH: 19. Known risks] |
| a one-shot `migrate` container | Runs Alembic before the API and workers start | [DB: 12. Migrations and change process] |

No ingress, reverse proxy or TLS terminator appears in the list. [ARCH: Containers (Docker Compose)] [ASSUMPTION PLT-05]

### 2.2 `startup-config-validation`

Everything required to run is validated at startup. A missing or invalid value stops the service at once with a clear message; no hidden default lets it boot with wrong config. Tuning values with a safe default may have defaults in code. Any fallback must be named, logged and visible. [ARCH: 15. Configuration]

| Kind | Settings named in the sources | Source |
|---|---|---|
| Required | Database URL and credentials; broker URL and credentials; Redis URL; storage credentials and bucket; the public storage URL used in presigned links; JWT signing secret, issuer and audience; `WORKER_JOB_TYPES` for workers | [ARCH: 15. Configuration] [ARCH: 8. Authentication and authorisation] [NOTEPAD: D31] |
| Tuning (defaults still to be written) | Lease length, heartbeat interval, worker concurrency, wait before a delivered message is handed back, sweep wait and cap, sweep batch size, retry delays and max attempts, active-jobs cap, request rate limits, presigned URL lifetime, file size cap, pending-file expiry, job and outbox retention, payload and result size caps, token lifetimes, refresh reuse window, absolute login lifetime | [ARCH: 15. Configuration] |

Which process needs which required setting is not stated. [ASSUMPTION PLT-01]

### 2.3 `migrate-job`

| Rule | Detail | Source |
|---|---|---|
| Tool | Alembic, created with the generator rather than by hand | [DB: 12. Migrations and change process] |
| When | A one-shot container runs before the API and workers start | [DB: 12. Migrations and change process] |
| Role | `qfe_migrator`, which can change the schema; running services never use it | [DB: 9. Performance and tuning plan] |
| Style | One migration per logical change; expand-and-contract; indexes with `CREATE INDEX CONCURRENTLY`; constraints added `NOT VALID` then validated; forward-only in production | [DB: 12. Migrations and change process] [NOTEPAD: D34] |
| CI | Migrations run on an empty database and an upgrade from the previous release is checked | [DB: 12. Migrations and change process] |

### 2.4 `database-roles`

`qfe_migrator`, `qfe_app` (reads and writes data only), and optionally `qfe_readonly` for dashboards. [DB: 9. Performance and tuning plan] Who creates the roles and the database at first start is not stated. [ASSUMPTION PLT-03]

### 2.5 Other settings the stack must carry

| Component | Setting | Source |
|---|---|---|
| SeaweedFS | The S3 gateway needs `-s3.externalUrl` (or correct forwarded headers) so presigned links work from outside Docker | [NOTEPAD: Phase 0 verification results] |
| RabbitMQ | `consumer_timeout` stays an explicit setting; default is 30 minutes | [ARCH: 11. Reliability and delivery] [NOTEPAD: Phase 0 verification results] |
| Postgres | `fillfactor = 80` on `jobs` and lowered autovacuum thresholds on `jobs`, `job_attempts` and `outbox` | [DB: 9. Performance and tuning plan] [DB: jobs; Table settings] |

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| Docker and Docker Compose | Container runtime | Runs the stack. The Windows development machine has Docker 29.5.2 and Compose 5.1.3 | [NOTEPAD: 2. Environment snapshot (checked 2026-10-08)] |
| Image registries | Images for the services | Exact tags are not pinned yet. Candidates exist for `postgres:18`, `python:3.14-slim`, `rabbitmq:4-management`, `redis:8` or `valkey/valkey:8`, `chrislusf/seaweedfs`, `node:22-slim` and the Grafana stack | [NOTEPAD: Phase 0 verification results] |

## 4. Data

**Tables:** it creates and changes the schema but reads and writes no rows of its own. [DB: 12. Migrations and change process]

**Persistent state to keep:** the Postgres data, RabbitMQ durable queues, SeaweedFS data, and Redis counters if persisted. Volumes, backups and Redis persistence are not described. [ARCH: Containers (Docker Compose)] [ASSUMPTION PLT-09]

**Who else touches it:** every container reads its configuration from here. [ARCH: 15. Configuration]

## 5. Internal workflow

### 5.1 Starting the stack

1. Postgres, RabbitMQ, Redis and storage start. [ARCH: Containers (Docker Compose)]
2. The `migrate` container applies migrations with the migrator role and exits. [DB: 12. Migrations and change process]
3. The API, relay, workers and maintenance start; each validates its configuration and stops if something required is missing. [ARCH: 15. Configuration]
4. Every process that knows a job type declares its queue at startup. [ARCH: 11. Reliability and delivery] Whether a process that cannot reach RabbitMQ at that moment refuses to start is not stated. [ASSUMPTION PLT-04]
5. Workers also check `WORKER_JOB_TYPES` and fail on an unknown type. [ARCH: Worker pools and concurrency (D35)]
6. The frontend starts. [ARCH: Containers (Docker Compose)]

### 5.2 Changing the schema while old code runs

1. Add the new column or table. [DB: 12. Migrations and change process]
2. Deploy code that handles both. [DB: 12. Migrations and change process]
3. Move data. [DB: 12. Migrations and change process]
4. Remove the old one in a later release. [DB: 12. Migrations and change process]

### 5.3 Changing a job type

1. A new type is registered in the API, relay and workers; its queue is declared by whichever process starts first. [ARCH: 11. Reliability and delivery]
2. Messages for it wait in its queue until a worker for that type starts. [ARCH: 11. Reliability and delivery]
3. Removing a type leaves its queue behind. [NOTEPAD: D28]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| A required setting is missing | The process does not start | None | [ARCH: 15. Configuration] |
| Migration fails | The API and workers must not start; the database may be partly changed | Partial schema change | [DB: 12. Migrations and change process] [ASSUMPTION PLT-08] |
| Two migrations run at once | Not guarded by anything described; the design relies on one one-shot container | Possible conflict | [DB: 12. Migrations and change process] [ASSUMPTION PLT-08] |
| RabbitMQ down at API startup | If queue declaration is fatal, the API cannot start, though submits do not need the broker | API unavailable during a broker outage | [ARCH: 11. Reliability and delivery] [DB: outbox] [ASSUMPTION PLT-04] |
| Old and new code run together | Safe only if migrations are expand-and-contract | Possible errors | [DB: 12. Migrations and change process] |
| The storage gateway is signed for an internal host | Presigned links fail from outside Docker | Unusable uploads | [NOTEPAD: Phase 0 verification results] |
| Application clocks differ from each other | Database time comparisons are unaffected; JWT expiry checks use each process's own clock and no leeway is stated | Early or late token expiry | [DB: 2. Conventions] [ASSUMPTION PLT-07] |
| Compose host is overloaded | The stack has about 14 or more containers | Slow or failing start | [ARCH: 19. Known risks] |

## 7. Concurrency and idempotency

- Migrations must run once; the `migrate` container is one-shot. [DB: 12. Migrations and change process] [ASSUMPTION PLT-08]
- Starting several copies of any service is safe where its part says so: workers by competing consumers, relays and `maintenance` by `SKIP LOCKED`, queue declaration by being idempotent. [ARCH: Containers (Docker Compose)] [ARCH: 11. Reliability and delivery]
- Starting the stack twice must leave the same result; role and bucket creation need to be repeatable. [ASSUMPTION PLT-03]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Weight:** all services in one Compose file is heavy on a development machine; the observability stack can be switched off. [ARCH: 19. Known risks]
- **Scaling knobs:** API and frontend scale horizontally, workers per pool, relays are "a small number", Postgres vertically with read replicas later, Redis single, later cluster. [ARCH: Containers (Docker Compose)]
- **Connections:** at the assumed number of worker processes, Postgres connection limits and PgBouncer's absence matter. [ASSUMPTION WK-10] [ASSUMPTION L-02]
- **Startup time** is not discussed. [ASSUMPTION PLT-04]

## 9. Security

- **Secrets** (database and broker credentials, storage keys, JWT signing secret) are required configuration. How they are delivered and rotated is not described. A rotated JWT secret would invalidate every token. [ARCH: 15. Configuration] [ARCH: 16. Security notes] [ASSUMPTION PLT-02]
- **Exposure:** clients upload straight to storage, so the storage gateway must be reachable from outside. The RabbitMQ management UI and Grafana are also in the stack. Which ports are published is not stated. [NOTEPAD: D31] [ARCH: Containers (Docker Compose)] [ASSUMPTION PLT-06]
- **TLS:** the refresh cookie is `Secure`, which needs HTTPS in production, and no TLS terminator or reverse proxy is listed. [ARCH: 8. Authentication and authorisation] [ASSUMPTION PLT-05]
- **Roles:** services use `qfe_app`, never the migrator. [DB: 9. Performance and tuning plan]
- **No global installs; dependencies only with approval.** [NOTEPAD: 1. Where we are now]

## 10. Open questions and deferred items

- Python 3.14 or 3.12, SQLAlchemy 2.1 or 2.0, Redis or Valkey, the S3 client path, and the integration test setup. [NOTEPAD: Phase 0 verification results] [ARCH: 18. Open items]
- Defaults for all tuning settings. [ARCH: 15. Configuration]
- Which process needs which setting; secret delivery and rotation; role and bucket bootstrap; ingress and TLS; published ports; backups and volumes; CI tool. [ASSUMPTION PLT-01] [ASSUMPTION PLT-02] [ASSUMPTION PLT-03] [ASSUMPTION PLT-05] [ASSUMPTION PLT-06] [ASSUMPTION PLT-09] [ASSUMPTION PLT-10]
- Tested down-migrations and partitioning. [DEFERRED: tested down-migrations] [DEFERRED: time partitioning of jobs]
- Trusted-proxy setting, needed as soon as an ingress exists. [DEFERRED: trusted-proxy setting and per-email login limit]
