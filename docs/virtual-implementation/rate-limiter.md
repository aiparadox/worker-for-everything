# rate-limiter

Part 5 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** Applies the request-rate limits, answers `429 Too Many Requests` when one is hit, and decides what to do when its store (Redis) is down. The counters live in Redis behind the `RateLimiter` port. [ARCH: 9. Rate limiting] [NOTEPAD: D17] It runs as middleware inside the `api` container. [ARCH: Containers (Docker Compose)]

**Does not do:**
- Count active jobs. That cap is counted in Postgres inside the submit transaction by [data-access#submit-job-tx]. [ARCH: 9. Rate limiting] [NOTEPAD: D29]
- Identify callers. [accounts-auth#verify-api-key] and [accounts-auth#verify-access-token] do. [ARCH: 8. Authentication and authorisation]
- Per-organisation limit overrides. [DEFERRED: per-organisation limit overrides]
- Read forwarded headers to find a client's real address. [DEFERRED: trusted-proxy setting and per-email login limit]
- Limit storage volume, queue depth or concurrent downloads. [ARCH: 9. Rate limiting] [ASSUMPTION RL-11]

## 2. Interfaces provided

### 2.1 `check-request-limit`

| Item | Detail | Source |
|---|---|---|
| Params | `limit_class` (R), and the identities needed by that class: API key id, organisation id, client IP, user id | [ARCH: 9. Rate limiting] |
| Returns | `allowed` with the numbers behind the rate limit headers, or `limited(retry_after)` | [ARCH: 9. Rate limiting] |
| Fallback | If the store is down: fail open or fail closed by class, with an error log, a metric and an alert on every fallback | [ARCH: 9. Rate limiting] |
| Where the fallback code lives | In one place, named for what it does, and logging every time it triggers | [ARCH: 9. Rate limiting] |

### 2.2 Limit classes

| Class | Applies to | When Redis is down | Source |
|---|---|---|---|
| Requests per API key | Each key | Fails open | [ARCH: 9. Rate limiting] |
| Requests per organisation | All keys of an organisation together | Fails open | [ARCH: 9. Rate limiting] |
| Login and signup per IP | The unauthenticated auth endpoints | Fails closed (requests rejected) | [ARCH: 9. Rate limiting] |
| Refresh and logout | Per IP and per user, separate from login | Fails open | [ARCH: 9. Rate limiting] [NOTEPAD: D40] |

The active-jobs cap is a fifth limit but lives elsewhere and does not depend on Redis. [ARCH: 9. Rate limiting]

How many limits live in Redis is stated differently in different places: "three request-rate limits" and "four limits" (and "all four limits"), while the table above has four Redis classes plus the Postgres cap. [ARCH: 9. Rate limiting] [ARCH: 17. Roadmap] [DB: 6. The active-jobs cap (D29)] [NOTEPAD: D17] [CONFLICT C-01]

Default numbers for every limit are not set. [ARCH: 9. Rate limiting] [ASSUMPTION RL-09] Which endpoint belongs to which class (for example the key-management calls) is not stated. [ASSUMPTION RL-02]

### 2.3 `rate-limit-response`

| Item | Detail | Source |
|---|---|---|
| Status | `429 Too Many Requests` | [ARCH: 9. Rate limiting] |
| Headers | `Retry-After`; ordinary responses carry rate limit headers whose names are not stated | [ARCH: 9. Rate limiting] [ASSUMPTION RL-03] |
| Body | A JSON error body whose fields are not stated | [ARCH: 9. Rate limiting] [ASSUMPTION RL-03] |
| Fail-closed answer | Requests are "rejected"; the status and body are not stated | [ARCH: 9. Rate limiting] [ASSUMPTION RL-04] |

The same answer shape is used when the active-jobs cap is hit, since all five are called limits. [ARCH: 9. Rate limiting] [ASSUMPTION A-10]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| Redis | Counters with expiry | The counts. Redis 8 is AGPLv3; Valkey is BSD and wire-compatible; the choice is open | [NOTEPAD: D17] [NOTEPAD: Phase 0 verification results] |
| `platform` | [platform#startup-config-validation] | Redis URL and credentials (required) and the limit values (tuning, with safe defaults) | [ARCH: 15. Configuration] [ARCH: 9. Rate limiting] |
| `observability` | [observability#trace-context] | Error log, metric and alert on every fallback | [ARCH: 9. Rate limiting] |

## 4. Data

**Redis only:** counters per limit class and identity. Counters expire on their own. [NOTEPAD: D17] No Postgres table is read or written. [DB: 7. Data that is not in Postgres]

**Who else touches them:** nothing else uses Redis. It is not used for the job queue. [NOTEPAD: D17]

## 5. Internal workflow

### 5.1 `check-request-limit`

1. Choose the class from the endpoint and build the counter key from its identity (key id, organisation id, IP or user id) and the current window. The algorithm (fixed window, sliding window or token bucket) is not stated; "counters expire on their own" points to expiring counters. [NOTEPAD: D17] [ASSUMPTION RL-01]
2. Increment the counter and set its expiry when it is new. [NOTEPAD: D17] Doing both atomically is not stated. [ASSUMPTION RL-01]
3. Compare with the limit. If over, return `limited` with a `Retry-After` value. How it is computed is not stated. [ARCH: 9. Rate limiting] [ASSUMPTION RL-10]
4. If Redis errors or times out, apply the fallback for the class: allow for classes that fail open, reject for login and signup, and log an error, count a metric and raise an alert. [ARCH: 9. Rate limiting]
5. Add the rate limit headers to the response. [ARCH: 9. Rate limiting]

### 5.2 Per-IP identity

The client address used is the connection's address, because forwarded headers are ignored in Phase 1. [ARCH: 9. Rate limiting]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Redis down, class fails open | Requests pass without a limit; error, metric and alert | No limit enforced | [ARCH: 9. Rate limiting] |
| Redis down, login or signup | Requests are rejected, so nobody can log in or sign up | None | [ARCH: 9. Rate limiting] |
| Redis slow but not down | Not described; every API request waits on the counter | Added latency on every request | [ASSUMPTION RL-05] |
| Redis restarts | Counters are lost and every limit resets | Limits briefly unenforced | [ASSUMPTION RL-08] |
| Behind a proxy or load balancer | All users share one address, so per-IP login limits lock out everyone after a few failures, or never bind a real attacker | Wrong enforcement | [ARCH: 9. Rate limiting] [DEFERRED: trusted-proxy setting and per-email login limit] |
| Invalid credentials | Not counted by any class: key limits need a valid key and the IP limits cover only login, signup, refresh and logout | Unlimited bogus requests | [ARCH: 9. Rate limiting] [ASSUMPTION RL-06] |
| Active-jobs cap reached | Handled by the submit transaction, not here | None | [ARCH: 9. Rate limiting] |

## 7. Concurrency and idempotency

- All API processes share the same counters in Redis, so the limit holds across copies of the API. [NOTEPAD: D17]
- Incrementing a counter must be atomic to avoid undercounting; the sources do not describe how. [ASSUMPTION RL-01]
- A retried request counts again. [ASSUMPTION RL-01]
- The fallback rule is the same for every API copy, because it lives in one place. [ARCH: 9. Rate limiting]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Cost per request:** at least two counter updates (key and organisation) on every API-key request, which can be sent together. With polling at about 1,000 reads per second plus submits, that is a few thousand Redis operations per second, which a single Redis handles. [ARCH: 9. Rate limiting] [ASSUMPTION JA-09]
- **Latency:** every request waits on Redis before it is served. A timeout is not described. [ASSUMPTION RL-05]
- **Hot keys:** one counter per organisation is hit by all that organisation's requests; one counter per IP is hit by everyone behind a proxy. [ARCH: 9. Rate limiting]
- **Memory:** one counter per active key, organisation, IP and user within a window; counters expire. [NOTEPAD: D17]
- **Single instance:** Redis is "single, later cluster". [ARCH: Containers (Docker Compose)]

## 9. Security

- **Who may call:** internal middleware only. [ARCH: Containers (Docker Compose)]
- **Protects against:** one key hammering the API, many keys dodging the key limit, password guessing and fake signups. [ARCH: 9. Rate limiting]
- **Gaps:** invalid credentials are not limited; per-IP limits misbehave behind proxies; forwarded headers are ignored to avoid spoofing. [ARCH: 9. Rate limiting] [ASSUMPTION RL-06]
- **Fail closed for login and signup** keeps a Redis outage from opening password guessing, at the cost of blocking all logins. [ARCH: 9. Rate limiting] [NOTEPAD: D18]
- IPv6 addresses and shared NAT addresses: grouping rules are not stated. [ASSUMPTION RL-07]

## 10. Open questions and deferred items

- Count of Redis limits across documents. [CONFLICT C-01]
- Trusted proxies and per-email login limit. [DEFERRED: trusted-proxy setting and per-email login limit]
- Per-organisation overrides. [DEFERRED: per-organisation limit overrides]
- Redis or Valkey. [NOTEPAD: Phase 0 verification results]
- Default values, algorithm, header names, body fields, fail-closed answer, timeouts, behaviour of a slow store, limits for bogus credentials. [ASSUMPTION RL-01] [ASSUMPTION RL-03] [ASSUMPTION RL-04] [ASSUMPTION RL-05] [ASSUMPTION RL-06] [ASSUMPTION RL-09]
