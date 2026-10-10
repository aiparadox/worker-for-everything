# GET /readyz

Tells whether the dependencies are reachable. Only a **critical** dependency being down makes the answer 503: PostgreSQL, the system of record. Any other dependency that is down (Valkey now; RabbitMQ and storage when their checks are added) is listed as `degraded` and the answer stays 200, so one partial outage does not pull every API copy out of rotation.

## Method and path

`GET /readyz`

## Path parameters

None.

## Query parameters

None.

## Headers

Request: none needed (`traceparent` is continued if present).

Response: `X-Trace-Id`.

## Request body

None.

## Responses

| Status | Meaning |
|---|---|
| 200 | Ready. `degraded` lists dependencies that are down but not critical. |
| 503 | Not ready: a critical dependency is down. |

Body (both statuses):

| Field | Type | Meaning |
|---|---|---|
| `status` | string | `ready` or `not_ready` |
| `degraded` | array of strings | names of non-critical dependencies that are down |
| `checks` | object | one entry per dependency: `status` (`ok` or `down`), `critical` (boolean), `duration_ms`, and `error` (only when down: the error class name or `timed out after 2s`, never a message that could contain a password) |

Each check has a 2 second limit; the checks run at the same time.

## Errors

None beyond the 503 above.

## Authentication and scopes

None. The endpoint is open.

## Rate limits

None.

## Examples

```
GET /readyz HTTP/1.1
```

```
HTTP/1.1 200 OK
content-type: application/json
x-trace-id: d3b9c2eb8d1cd640573393d20702dc04

{"status":"ready","degraded":[],"checks":{"postgres":{"status":"ok","critical":true,"duration_ms":26},"valkey":{"status":"ok","critical":false,"duration_ms":22}}}
```

With Valkey down:

```
HTTP/1.1 200 OK

{"status":"ready","degraded":["valkey"],"checks":{"postgres":{"status":"ok","critical":true,"duration_ms":3},"valkey":{"status":"down","critical":false,"duration_ms":2,"error":"ConnectionError"}}}
```
