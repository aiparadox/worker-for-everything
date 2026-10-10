# observability

Part 13 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** One contract that every process follows so that logs, metrics and traces for one request or one job can be joined: a trace id that travels from the API through the database and RabbitMQ into the worker, JSON logs with fixed fields, metrics, alerts and health endpoints. [ARCH: 12. Observability] The stack behind it is the OpenTelemetry collector, Tempo, Loki, Prometheus and Grafana. [ARCH: 12. Observability]

**Does not do:**
- Business logic of any kind. [ARCH: 12. Observability]
- An audit log of who did what to which key or user. [DEFERRED: audit log]
- Billing or usage metering. [DEFERRED: billing and usage metering]
- Log payload or document content. Logs record ids and sizes. [ARCH: 16. Security notes]

## 2. Interfaces provided

### 2.1 `trace-context`

| Rule | Detail | Source |
|---|---|---|
| In | Every request gets a trace id in the W3C `traceparent` format; if the client sends none, one is generated | [ARCH: 12. Observability] |
| Out | The trace id is returned in the `X-Trace-Id` response header | [ARCH: 12. Observability] |
| Stored | Saved on the job as `jobs.trace_id` (32 hex characters), copied to `job_attempts.trace_id`, and written into `outbox.headers` | [DB: jobs.trace_id] [DB: job_attempts.trace_id] [DB: outbox.headers] |
| Over the broker | Sent as a RabbitMQ message header | [ARCH: 12. Observability] |
| Continued | The relay and the worker continue the same trace, so API, relay and worker log lines for one job share one trace id | [ARCH: 12. Observability] |
| Which trace a recovery or sweep row carries | Not stated | [ASSUMPTION OBS-01] |
| Span links across processes | Only the trace id is stored on rows and messages, not a parent span id | [DB: outbox.headers] [ASSUMPTION OBS-02] |
| Validation of a client-supplied value | Not stated | [ASSUMPTION OBS-09] |

### 2.2 `log-format`

Structured JSON. Every line carries `trace_id` and `span_id`, and where known `org_id` and `job_id`. [ARCH: 12. Observability] Logs record ids and sizes, not content, and secrets are never logged. [ARCH: 16. Security notes]

### 2.3 `metrics-endpoint`

`/metrics` exposes: request rate and latency, queue depth per job type, job duration by type, retries, `jobs_failed_total` by job type and error code, sweep re-queues, stuck outbox rows, rate limit rejections, and Valkey fallback events. `job_type` is a safe label; `org_id` and `job_id` are not. [ARCH: 12. Observability] RabbitMQ's own Prometheus metrics supply queue depth and consumer counts. [ARCH: 12. Observability] [NOTEPAD: D28] The Postgres exporter supplies connections, locks, replication lag, bloat and slow queries. [DB: 9. Performance and tuning plan] Which processes expose the endpoint is not stated. [ASSUMPTION A-12]

### 2.4 `health-endpoints`

`/healthz` says the process is up; `/readyz` says its dependencies are reachable. [ARCH: 12. Observability] Which dependencies `/readyz` checks, and which processes serve these paths, is not stated. [ASSUMPTION OBS-06]

### 2.5 `alert-rules`

| Alert | Source |
|---|---|
| A queue has messages but no consumers | [ARCH: 12. Observability] [NOTEPAD: D28] |
| Queue depth growing per job type | [ARCH: 12. Observability] |
| Elevated failed-job rate | [ARCH: 12. Observability] [NOTEPAD: D25] |
| Sweep re-queues | [ARCH: 12. Observability] [NOTEPAD: D27] |
| A stuck outbox row | [ARCH: 12. Observability] |
| Valkey fallback | [ARCH: 12. Observability] [ARCH: 9. Rate limiting] |
| Elevated error rates | [ARCH: 12. Observability] |

Thresholds and who is notified are not stated. [ASSUMPTION OBS-05]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| OpenTelemetry collector | OTLP export of traces, logs and metrics | Collector fans out to Tempo (traces), Loki (logs), Prometheus (metrics), Grafana on top [ARCH: 12. Observability] |
| Prometheus | Scrapes `/metrics` and RabbitMQ and Postgres exporters | [ARCH: 12. Observability] [DB: 9. Performance and tuning plan] [ASSUMPTION A-12] |
| `platform` | [platform#startup-config-validation] | Collector endpoint and sampling settings, if any [ARCH: 15. Configuration] |

The stack may be switched off for light local work. [ARCH: 19. Known risks] Compatibility between Grafana, Loki, Tempo, Prometheus and the collector was not verified. [NOTEPAD: Phase 0 verification results] [ASSUMPTION OBS-11]

## 4. Data

**Tables:** none of its own. It relies on three columns: `jobs.trace_id`, `job_attempts.trace_id` and `outbox.headers`. [DB: jobs.trace_id] [DB: job_attempts.trace_id] [DB: outbox.headers]

**Who else touches them:** [data-access#submit-job-tx] writes the first trace id; the worker and relay read it. [DB: jobs; §5 Submit job]

## 5. Internal workflow

1. **Request enters the API:** read `traceparent`; if absent or invalid, generate a trace id. [ARCH: 12. Observability] [ASSUMPTION OBS-09]
2. Put the trace id and span id in the logging context, and add `org_id` once known. [ARCH: 12. Observability]
3. **Submit:** pass the trace id to [data-access#submit-job-tx]; it lands in `jobs.trace_id` and the outbox headers. [DB: jobs.trace_id] [DB: outbox.headers]
4. **Respond:** set `X-Trace-Id`. [ARCH: 12. Observability]
5. **Relay:** copy headers to the message. [DB: outbox.headers]
6. **Worker:** read the header (or the job's `trace_id` from the claim), set the context, and give handlers a logger tagged with it. [ARCH: 10. Job types and handlers (how new work plugs in)] [ARCH: 12. Observability]
7. **Recovery and sweep rows:** carry the job's stored trace id. [DB: outbox.headers] [ASSUMPTION OBS-01]
8. **Export:** send spans, logs and metrics to the collector. [ARCH: 12. Observability]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Collector, Tempo, Loki or Prometheus down | Whether processes keep serving without blocking on export is not stated | Gaps in telemetry | [ASSUMPTION OBS-08] |
| Missing or malformed `traceparent` | A new trace id is generated | New trace | [ARCH: 12. Observability] |
| Client sends a trace id it chose | Logs of this request carry that value | Possible correlation noise | [ASSUMPTION OBS-09] |
| `/readyz` includes Valkey or RabbitMQ | An outage of either would make the API look unready, though submits do not need the broker and the Valkey limits fail open by design | Possible self-inflicted API outage | [ARCH: 9. Rate limiting] [DB: outbox] [ASSUMPTION OBS-06] |
| Alert thresholds missing | Alerts cannot fire | Silent failures | [ASSUMPTION OBS-05] |
| `/metrics` unreachable from Prometheus | No metrics for that process | Blind spot | [ASSUMPTION A-12] |

## 7. Concurrency and idempotency

- The trace id belongs to the request or job and is carried explicitly; concurrent requests do not share it. [ARCH: 12. Observability]
- A job's trace id is fixed at submit and reused for every attempt, so one trace can span hours or days of retries. [DB: jobs.trace_id] [DB: job_attempts.trace_id] [ASSUMPTION OBS-01]
- Metrics are counters and gauges that tolerate several writers. [ARCH: 12. Observability]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Log volume:** one or more lines per request across the API, relay, worker and maintenance; at about 1,000 reads per second from polling, that is large for Loki. A sampling or level policy is not stated. [ARCH: 12. Observability] [ASSUMPTION JA-09] [ASSUMPTION OBS-03]
- **Traces:** whether every request is traced or a sample is not stated. [ASSUMPTION OBS-03]
- **Metric cardinality:** `job_type` is a safe label, but `error code` has no defined, bounded list. [ARCH: 12. Observability] [ASSUMPTION OBS-04]
- **Heartbeats and claims** could add log lines per job per few seconds. [DB: 8. Write load and size limits] [ASSUMPTION OBS-03]
- **Export cost** should stay off the request path. [ASSUMPTION OBS-08]

## 9. Security

- **Who may call:** `/metrics` and the health paths are for monitoring; who may reach them is not stated. [ASSUMPTION A-12]
- **Content:** no payloads, document content or secrets in logs. [ARCH: 16. Security notes]
- **Personal data:** login failures and signups naturally involve emails and IP addresses; whether they are logged is not stated. [ARCH: 16. Security notes] [ASSUMPTION OBS-10]
- **Trace id exposure:** the trace id is returned to clients in a response header. [ARCH: 12. Observability]
- **Grafana access** and log retention are not described. [ASSUMPTION OBS-05]

## 10. Open questions and deferred items

- Audit log, and billing or usage metering. [DEFERRED: audit log] [DEFERRED: billing and usage metering]
- Which processes expose `/metrics` and the health paths. [ASSUMPTION A-12]
- Readiness rules, alert thresholds and routing, sampling, label rules, PII in logs, export failure behaviour. [ASSUMPTION OBS-03] [ASSUMPTION OBS-04] [ASSUMPTION OBS-05] [ASSUMPTION OBS-06] [ASSUMPTION OBS-08] [ASSUMPTION OBS-10]
- Image versions and compatibility of the Grafana stack, and the optional all-in-one `grafana/otel-lgtm` image for local use. [NOTEPAD: Phase 0 verification results]
