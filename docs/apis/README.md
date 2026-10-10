# API reference

One file per endpoint, named from the method and path: `POST /v1/jobs` is `post-v1-jobs.md`. A test (`backend/tests/unit/test_api_docs.py`) fails when a route has no file, when a file has no route, when a file is missing a required heading, or when a file is not listed here. Start a new endpoint file from [`_TEMPLATE.md`](_TEMPLATE.md).

## Operational endpoints (open, no credentials)

- [`GET /healthz`](get-healthz.md): the process is running.
- [`GET /readyz`](get-readyz.md): dependencies are reachable (503 only when PostgreSQL is down).
- [`GET /metrics`](get-metrics.md): Prometheus metrics.

The endpoints for accounts, API keys, jobs and files are added with their tasks.
