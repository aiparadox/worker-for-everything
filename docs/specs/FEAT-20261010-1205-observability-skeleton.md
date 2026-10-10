# FEAT-20261010-1205: observability skeleton and the first running API

Status: **draft for approval**. Working branch: `feat-20261010-1205-observability-skeleton`, from `master` after `FEAT-1204`. Depends on: `FEAT-20261010-1202`, `FEAT-20261010-1203`, `FEAT-20261010-1204`, `FEAT-20261010-1208`.

## 1. What this builds and why

The parts every later task relies on: JSON logs where every line carries a trace id, the trace id returned to clients, `/healthz`, `/readyz` and `/metrics`, and OpenTelemetry export. It also creates the first running `api` service (an app factory with only these endpoints), because these endpoints need a process to live in. Business endpoints come later. Dashboards and alerts are `FEAT-1223`, not here.

## 2. Verified facts (from the design) and what is not verified

- Rules from `ARCHITECTURE.md` section 12: W3C `traceparent`; trace id returned in `X-Trace-Id`; structured JSON logs with `trace_id`, `span_id` and, where known, `org_id` and `job_id`; `job_type` is a safe metric label, `org_id` and `job_id` are not; `/healthz` means the process is up, `/readyz` means dependencies are reachable. Section 16: logs record ids and sizes, never content, secrets or tokens.
- `grafana/otel-lgtm` accepts OTLP on 4317 (gRPC) and 4318 (HTTP) (read from its README today).
- **Not verified:** that the beta OpenTelemetry instrumentation packages (0.66b1) work with FastAPI, SQLAlchemy 2.1 and asyncpg on Python 3.12. This task finds out. If one fails, it is dropped and the manual spans stay.

## 3. Proposal

### 3.1 Logging

- `structlog` writing one JSON object per line to standard output. Fields: `timestamp` (UTC), `level`, `event`, `service`, `trace_id`, `span_id`, plus `org_id` and `job_id` when set. A processor adds `trace_id` and `span_id` from the current OpenTelemetry span.
- `org_id` and `job_id` are bound through context variables, so code deep in a call can log them without passing them down.
- A redaction processor replaces the value of any key named like `password`, `secret`, `token`, `authorization`, `api_key` or `cookie`. A test proves a secret passed by mistake does not appear.
- Standard-library and uvicorn log lines go through the same JSON format, so there is no second format in the output.

### 3.2 Trace id

- Middleware reads `traceparent`. A valid one is continued; a missing or invalid one starts a new trace (never an error).
- The trace id (32 hex characters) is returned in `X-Trace-Id` on every response, including errors.
- Small helpers for later tasks: get the current trace id, produce a `traceparent` string for storing on a job or putting in a message header, and a context manager that continues a trace from a stored `traceparent` (used by the relay and worker).

### 3.3 Health and metrics endpoints

- `GET /healthz`: returns 200 if the process is running. Checks nothing else.
- `GET /readyz`: runs the registered dependency checks at the same time, each with a short timeout (2 s). A check is a small function registered by the module that owns the dependency. **This task registers Postgres and Valkey checks** (a plain connection test and `PING`), which also gives the first real run of the `redis` client against Valkey. RabbitMQ and storage checks are registered by `FEAT-1213` and `FEAT-1214`.
- **My recommendation, please confirm:** `/readyz` returns 503 only when **Postgres** is down, because the API cannot do its job without the system of record. Any other dependency that is down is listed in the response as `degraded`, with status 200. Reason: the design already lets submits work without the broker (outbox) and lets most rate limits fail open, so pulling every API copy out of rotation because RabbitMQ or Valkey is down would turn a partial problem into a full outage. The response body lists every check so a person or an alert can see it.
- `GET /metrics`: Prometheus text format from `prometheus-client`. Skeleton metrics: HTTP request count and duration (labels: method, route template, status class; never the raw path or ids). Naming rule: prefix `qfe_`; no `org_id`, `job_id` or user ids as labels. Domain metrics (queue depth, failed jobs, sweep re-queues, stuck outbox rows) are added by the tasks that own them.
- Processes that are not web servers (worker, relay, maintenance) get a helper that starts a tiny metrics-only HTTP server on a configurable port, so they can be scraped too.
- `/metrics` is open in development. Protecting it belongs to the deferred production work (`WISH-20261010-1309`).

### 3.4 OpenTelemetry

- Traces exported over OTLP to the endpoint in config (`FEAT-1203` setting). Automatic spans for FastAPI, SQLAlchemy and asyncpg through the instrumentation packages; manual spans are used where those are missing.
- **Telemetry on or off is an explicit setting**, not a silent fallback: `QFE_TELEMETRY=on|off`. `off` is logged once at startup ("telemetry disabled by configuration"), and is used in unit tests. When `on`, the OTLP endpoint is required. This updates the table in `FEAT-1203`.
- Logs go to Loki through standard output collected by the container runtime in the full stack, or are viewed with `docker compose logs`; the apps do not push logs themselves in Phase 0. (Whether `otel-lgtm` picks up Docker logs without extra agent configuration is **not verified**; if not, the app exports logs over OTLP too, which the OTel SDK supports. Decided when tried.)

### 3.5 The `api` service

`qfe.api.create_app()` builds the FastAPI app with the middleware and the three endpoints above. The `api` service is added to `compose.yaml` (same backend image, command `uvicorn`), after `migrate`. Its health check calls `/healthz`.

## 4. Tests

- Unit: log lines are valid JSON with the required fields; redaction works; `traceparent` valid, missing and malformed cases; `X-Trace-Id` equals the id in the log lines of that request.
- Unit: `/readyz` with fake checks: all ok → 200; Postgres down → 503; Valkey down → 200 with `degraded`; one check hanging → returns within the timeout.
- Integration (Compose test profile): `/readyz` against real Postgres and Valkey; stopping Valkey flips it to `degraded`; `/metrics` shows the request counter after a call; a span reaches `otel-lgtm` (checked by querying Tempo's API through Grafana's port, or by inspecting the collector, whichever the image exposes; decided when tried).

## 5. Check for the same problem elsewhere

Lateral: the trace id and JSON log rules apply to **every** process, so the helpers live in `qfe.observability`, not in the API package, and the unit tests run them through a fake non-web process too. Redaction is checked on the standard-library and uvicorn paths as well as structlog's own. Causal depth: "no trace id in a log line" has three causes — no active span, a log written outside the request context, and a log written by a library; all three are covered by tests.

## 6. Out of scope

Dashboards and alerts (`FEAT-1223`), domain metrics, the RabbitMQ and storage readiness checks, protecting `/metrics`, log shipping to Loki beyond what the image does by itself.

## 7. Questions for you

1. `/readyz` fails only when Postgres is down; other dependencies show as `degraded` (my recommendation). OK?
2. `QFE_TELEMETRY=on|off` as an explicit, logged setting, with the endpoint required when `on`. OK?
