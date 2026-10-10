# GET /metrics

Prometheus metrics of the API process, in the Prometheus text format.

## Method and path

`GET /metrics`

## Path parameters

None.

## Query parameters

None.

## Headers

Request: none needed.

Response: `Content-Type: text/plain; version=1.0.0; charset=utf-8` and `X-Trace-Id`.

## Request body

None.

## Responses

| Status | Body |
|---|---|
| 200 | Prometheus text format |

Metrics now: `qfe_http_requests_total{method, route, status_class}` and `qfe_http_request_duration_seconds{method, route}` (a histogram). `route` is the route template (for example `/v1/jobs/{id}`), `unmatched` for unknown paths, never the raw path. Rule for all metrics: prefix `qfe_`; never use an organisation id, job id or user id as a label; `job_type` is allowed. More metrics are added by the tasks that own them.

## Errors

None.

## Authentication and scopes

None in development. Protecting this endpoint is part of the deferred production work.

## Rate limits

None.

## Examples

```
GET /metrics HTTP/1.1
```

```
HTTP/1.1 200 OK
content-type: text/plain; version=1.0.0; charset=utf-8

qfe_http_requests_total{method="GET",route="/healthz",status_class="2xx"} 2.0
qfe_http_requests_total{method="GET",route="/readyz",status_class="2xx"} 1.0
```
