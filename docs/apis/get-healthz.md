# GET /healthz

Tells whether the process is running. Used by container health checks. It checks nothing else; use [`GET /readyz`](get-readyz.md) to check dependencies.

## Method and path

`GET /healthz`

## Path parameters

None.

## Query parameters

None.

## Headers

Request: none needed. A W3C `traceparent` header is continued if present; a missing or malformed one starts a new trace and is never an error.

Response: `X-Trace-Id`, the 32-character trace id of this request.

## Request body

None.

## Responses

| Status | Body |
|---|---|
| 200 | `{"status": "ok"}` |

## Errors

None. If the process is not running there is no response at all.

## Authentication and scopes

None. The endpoint is open.

## Rate limits

None.

## Examples

```
GET /healthz HTTP/1.1
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

```
HTTP/1.1 200 OK
content-type: application/json
x-trace-id: 4bf92f3577b34da6a3ce929d0e0e4736

{"status":"ok"}
```
