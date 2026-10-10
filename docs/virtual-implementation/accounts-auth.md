# accounts-auth

Part 2 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

## 1. Purpose and non-responsibilities

**Purpose.** Everything about who is calling: signup, login, token refresh, logout, organisations and memberships, the lifecycle of API keys, and the checks that turn a bearer credential into an organisation and a set of scopes. There are two credential kinds, kept apart on purpose: a browser login (an access token plus a refresh cookie) and an API key. [ARCH: 8. Authentication and authorisation] It runs inside the `api` container. [ARCH: Containers (Docker Compose)]

**Does not do:**
- Rate limiting; [rate-limiter#check-request-limit] does that. [ARCH: 9. Rate limiting]
- Email verification, password reset, member invitations or account recovery. [DEFERRED: email verification and the email sender] [DEFERRED: password reset and member invitations] [DEFERRED: account recovery]
- OAuth providers. [DEFERRED: OAuth login providers] The port exists so they can be added later. [ARCH: 6. Code structure and the adapter rule]
- Per-endpoint authorisation of jobs and files. Callers use [accounts-auth#verify-api-key] and decide with the scopes it returns. [ARCH: 8. Authentication and authorisation]
- Organisation switching for users in several organisations. [NOTEPAD: 10. Open items]
- Deleting organisations or users. [DEFERRED: organisation and user deletion flow]

## 2. Interfaces provided

Paths, wire formats and status codes are not defined in the sources beyond the endpoint names; only the names signup, login, refresh, logout, and create, list and revoke API keys are listed. [ARCH: 14. API documentation rules] [ASSUMPTION A-02] Errors are JSON bodies, as stated for the 429 case. [ARCH: 9. Rate limiting]

### 2.1 `signup`

| Item | Detail | Source |
|---|---|---|
| Caller | Anyone, from `frontend` | [ARCH: 8. Authentication and authorisation] |
| Fields | `email` (R), `password` (R), `display_name` (O) | [DB: users] [DB: auth_identities.secret_hash] [DB: users.display_name] |
| Validation | Any email address is accepted, because verification is deferred. Email format and the password rules (minimum length and so on) are not stated | [ARCH: 8. Authentication and authorisation] [DB: 4.2 users] [ASSUMPTION AA-02] |
| Effect | Creates the user, a `password` identity, a first organisation and an `owner` membership. Where the organisation name comes from is not stated | [NOTEPAD: D30] [DB: memberships.role] [ASSUMPTION AA-01] |
| Response | Not stated whether signup also logs the user in | [ASSUMPTION AA-03] |
| Errors | Email already taken; invalid input; rate limited (429) | [DB: users] [ARCH: 9. Rate limiting] |
| Limit | Login and signup per IP, which fails closed when Valkey is down | [ARCH: 9. Rate limiting] |

### 2.2 `login`

| Item | Detail | Source |
|---|---|---|
| Fields | `email` (R), `password` (R) | [DB: auth_identities.secret_hash] |
| Response | An access token (a signed JWT of about 15 minutes with claims `iss`, `aud`, `sub`, `exp`, `iat`, `jti`, `org_id`, `role`, `fam`) in the body, and the refresh token as an httpOnly, Secure, `SameSite=Strict` cookie sent only to the refresh path | [ARCH: 8. Authentication and authorisation] |
| Errors | Wrong credentials; disabled user; rate limited. Whether the answer for an unknown email differs from a wrong password is not stated | [DB: users.status] [ASSUMPTION AA-04] |
| Limit | Login and signup per IP, fails closed. Per-email limit is deferred | [ARCH: 9. Rate limiting] [DEFERRED: trusted-proxy setting and per-email login limit] |

### 2.3 `refresh`

| Item | Detail | Source |
|---|---|---|
| Input | The refresh cookie only | [ARCH: 8. Authentication and authorisation] |
| Response | A new access token and a new refresh cookie; the old refresh token is marked used | [ARCH: 8. Authentication and authorisation] [DB: refresh_tokens.used_at] |
| Distinct error | A used token shown again within the reuse window gets an "already refreshed" error and nothing is revoked | [ARCH: 8. Authentication and authorisation] [ASSUMPTION AA-10] |
| Errors | Reuse after the window (family revoked), family expired (`family_expires_at` passed), revoked, expired | [DB: refresh_tokens.family_expires_at] [DB: refresh_tokens.revoked_at] |
| Limit | Its own limit, separate from login, per IP and per user; fails open | [ARCH: 9. Rate limiting] [NOTEPAD: D40] |

### 2.4 `logout`

Revokes the token family; the access token stays valid until it expires, at most about 15 minutes. [ARCH: 8. Authentication and authorisation] How the family is identified (refresh cookie or the `fam` claim) is not stated. [ASSUMPTION A-05] Its limit is light, per IP and per user, and fails open. [ARCH: 9. Rate limiting] [NOTEPAD: D40]

### 2.5 `create-api-key`

| Item | Detail | Source |
|---|---|---|
| Caller | A browser login (access token). API keys cannot create or revoke keys | [ARCH: 8. Authentication and authorisation] |
| Fields | `name` (R, 1 to 100 characters), `scopes` (R, a subset of `jobs:read`, `jobs:write`, `files:read`, `files:write`), `expires_at` (O) | [DB: api_keys.name] [DB: api_keys.scopes] [DB: api_keys.expires_at] |
| Pre-check | Re-reads the user and membership from the database on every call, so a role change takes effect at once. Which roles may create keys is not stated | [ARCH: 8. Authentication and authorisation] [ASSUMPTION AA-05] |
| Response | The full key `qfe_<prefix>_<random secret>`, shown once, with the key id, prefix, name, scopes and expiry | [ARCH: 8. Authentication and authorisation] [DB: api_keys.key_prefix] |
| Limit | Which request limit covers it is not stated | [ASSUMPTION A-08] |

### 2.6 `list-api-keys` and `revoke-api-key`

`list-api-keys` returns an organisation's keys without hashes, including revoked and expired ones, which are kept. `revoke-api-key` sets `revoked_at` and takes effect on the next request. Both are browser-login calls that re-read the membership. [DB: api_keys.revoked_at] [DB: api_keys] [ARCH: 8. Authentication and authorisation] No limit on the number of keys is stated. [ASSUMPTION AA-09]

### 2.7 `verify-api-key` (internal)

| Item | Detail | Source |
|---|---|---|
| Input | The bearer string `qfe_<prefix>_<secret>` | [ARCH: 8. Authentication and authorisation] |
| Returns | Organisation id, key id and scopes, or `unauthenticated` | [DB: api_keys.scopes] [DB: api_keys.organisation_id] |
| Checks | Prefix lookup, constant-time comparison of the SHA-256 hash, not revoked, not expired. Whether a suspended organisation or a disabled creator blocks the key is not stated | [ARCH: 8. Authentication and authorisation] [DB: organisations.status] [ASSUMPTION AA-12] |
| Side effect | `last_used_at` written at most once per interval | [DB: api_keys.last_used_at] |

### 2.8 `verify-access-token` (internal)

Checks the signature, issuer, audience and expiry, and that the token type is an access token and not a refresh token. Returns the user id, organisation id, role and family. [ARCH: 8. Authentication and authorisation] It does not check a denylist, so a logged-out token works until it expires. [DEFERRED: access-token denylist] The role claim can be stale for up to about 15 minutes except where the membership is re-read. [ARCH: 8. Authentication and authorisation] [ASSUMPTION AA-11]

### 2.9 Telling the two credentials apart

Both travel as `Authorization: Bearer`. How the API decides whether a bearer string is an API key or a JWT is not stated; the `qfe_` prefix is the visible difference. [ARCH: 8. Authentication and authorisation] [ASSUMPTION A-07]

### 2.10 Origin check

State-changing requests get an origin check, as the minimum CSRF protection beside `SameSite` cookies. Which part implements it and which origins are allowed is not stated. [ARCH: 16. Security notes] [ASSUMPTION AA-07]

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| `data-access` | [data-access#create-user-with-org], [data-access#find-password-identity], [data-access#record-login] | Signup and login |
| `data-access` | [data-access#insert-refresh-token], [data-access#rotate-refresh-token], [data-access#revoke-token-family] | Refresh and logout |
| `data-access` | [data-access#read-membership], [data-access#create-api-key-row], [data-access#list-api-key-rows], [data-access#revoke-api-key-row] | Key management |
| `data-access` | [data-access#find-api-key-by-prefix], [data-access#touch-api-key-last-used] | `verify-api-key` |
| `rate-limiter` | [rate-limiter#check-request-limit] | Applied to its own endpoints |
| `platform` | [platform#startup-config-validation] | JWT signing secret, issuer, audience and the lifetimes |
| `observability` | [observability#trace-context] | Logs and metrics |

Sources: [ARCH: 8. Authentication and authorisation] [DB: 5. How the main operations touch the database] [ARCH: 15. Configuration]

The libraries are PyJWT and `pwdlib` with Argon2, behind the `AuthProvider` port, not yet added or approved. [NOTEPAD: D33] [ARCH: 8. Authentication and authorisation]

## 4. Data

**Reads and writes (through `data-access`):** `users`, `auth_identities`, `organisations`, `memberships`, `refresh_tokens`, `api_keys`. [DB: 3. Entity overview]

**Notable columns:** `auth_identities.provider_subject` is the user's own id for passwords; `refresh_tokens.family_id`, `family_expires_at`, `used_at`, `replaced_by`, `revoked_at`; `api_keys.key_prefix`, `key_hash`, `scopes`, `revoked_at`, `expires_at`, `last_used_at`; `memberships.role`; `organisations.status`; `users.status`. [DB: auth_identities.provider_subject] [DB: refresh_tokens.family_id] [DB: api_keys.key_prefix] [DB: memberships.role] [DB: organisations.status] [DB: users.status]

**Who else touches them:** `maintenance` deletes expired or revoked refresh tokens; no other part writes these tables. [DB: 10. Retention and cleanup; refresh_tokens]

## 5. Internal workflow

### 5.1 Signup

1. Apply the signup limit. [ARCH: 9. Rate limiting]
2. Validate the fields. [ASSUMPTION AA-02]
3. Hash the password with Argon2. [ARCH: 8. Authentication and authorisation]
4. Call [data-access#create-user-with-org]. [NOTEPAD: D30]
5. Return the result; whether this also logs the user in is not stated. [ASSUMPTION AA-03]

### 5.2 Login

1. Apply the login limit. [ARCH: 9. Rate limiting]
2. [data-access#find-password-identity]; verify the Argon2 hash; reject a disabled user. [DB: users.status]
3. Create a new `family_id` and `family_expires_at`; call [data-access#insert-refresh-token]; call [data-access#record-login]. [DB: refresh_tokens.family_expires_at] [DB: users.last_login_at]
4. Sign the access token and the refresh token; set the cookie with the refresh path. [ARCH: 8. Authentication and authorisation]

### 5.3 Refresh

1. Apply the refresh limit. [ARCH: 9. Rate limiting]
2. Verify the refresh JWT (signature, audience, `typ: refresh`). [ARCH: 8. Authentication and authorisation]
3. Call [data-access#rotate-refresh-token] with the reuse window. [DB: refresh_tokens; §5 Refresh token]
4. On `rotated`, sign a new access token and set a new cookie. On `already-refreshed`, return the distinct error. On `reuse-detected`, `family-expired`, `revoked` or `expired`, return unauthenticated. [ARCH: 8. Authentication and authorisation]

### 5.4 Create an API key

1. Verify the access token. [ARCH: 8. Authentication and authorisation]
2. [data-access#read-membership]; check the user is active and allowed. [ARCH: 8. Authentication and authorisation] [ASSUMPTION AA-05]
3. Generate a random prefix and a random secret; the key is `qfe_<prefix>_<secret>`. The secret is random and unrelated to any UUID. [ARCH: 8. Authentication and authorisation] The lengths are not stated. [ASSUMPTION AA-08]
4. Hash the full key with SHA-256. [DB: api_keys.key_hash]
5. [data-access#create-api-key-row]; on a prefix collision, retry with a new prefix. [DB: api_keys.key_prefix] [ASSUMPTION DA-04]
6. Return the full key once; it is never stored. [ARCH: 8. Authentication and authorisation]

### 5.5 `verify-api-key`

1. Split the bearer string into prefix and secret. [ARCH: 8. Authentication and authorisation]
2. [data-access#find-api-key-by-prefix]. [DB: api_keys.key_prefix]
3. Compare the hash in constant time. [ARCH: 8. Authentication and authorisation]
4. Reject if revoked or expired. [DB: api_keys.revoked_at] [DB: api_keys.expires_at]
5. Call [data-access#touch-api-key-last-used]. [DB: api_keys.last_used_at]
6. Return the principal (organisation, key, scopes). [DB: api_keys.scopes]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Signup writes fail midway | If the four inserts are one transaction nothing is left; if not, a user without an organisation is possible | None, or a partial account | [ASSUMPTION DA-03] |
| Two signups with the same email | The unique index on `lower(email)` lets one win | None | [DB: users] |
| Login: database down | Login fails; existing access tokens keep working until they expire | None | [ARCH: 8. Authentication and authorisation] |
| Refresh: reuse after the window | Whole family revoked; the user logs in again | Revoked tokens | [DB: refresh_tokens.revoked_at] |
| Refresh: Valkey down | Refresh limits fail open, so refresh keeps working | None | [ARCH: 9. Rate limiting] |
| Login or signup: Valkey down | Rejected (fail closed) | None | [ARCH: 9. Rate limiting] |
| Key creation: prefix collision | Retried with a new prefix | None | [ASSUMPTION DA-04] |
| `verify-api-key`: database down | Every API-key call fails; no job can be submitted or read | None | [DB: 1. Principles] |
| Revoked key in use | Rejected on the next request | None | [DB: api_keys.revoked_at] |
| Logged-out access token | Still accepted until it expires | None | [ARCH: 8. Authentication and authorisation] |
| Signing secret missing or invalid | The service does not start | None | [ARCH: 8. Authentication and authorisation] |

## 7. Concurrency and idempotency

- Two refreshes with the same token: one rotates, the other falls in the reuse window, if the first has committed. [DB: refresh_tokens; §5 Refresh token] [ASSUMPTION DA-14]
- Logout and revoke can be repeated safely. [ASSUMPTION DA-17]
- Two key creations with the same prefix: the unique index rejects one, and it retries. [DB: api_keys.key_prefix]
- Revoking a key does not stop requests already past verification. [ASSUMPTION AA-16]
- The `last_used_at` write is throttled so a burst from one key does not hammer one row. [DB: api_keys.last_used_at]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-01]

- **Every API-key request** costs one database read by prefix plus a SHA-256; no cache is described. [ARCH: 8. Authentication and authorisation] [ASSUMPTION DA-18]
- **Login and signup** hash with Argon2, which is deliberately slow and memory-hungry; whether it runs off the event loop and what parameters it uses is not stated. Combined with a per-IP limit that does not work behind a proxy, a flood of logins can exhaust CPU. [ARCH: 8. Authentication and authorisation] [ARCH: 9. Rate limiting] [ASSUMPTION AA-13]
- **Page reloads** require a refresh, because the access token is only in memory, so refresh traffic scales with page views, not with logins. [ARCH: 8. Authentication and authorisation] [ASSUMPTION A-06]
- **JWT checks** are local CPU work. [ARCH: 8. Authentication and authorisation]
- **Unbounded:** `list-api-keys` has no stated limit. [ASSUMPTION AA-09]
- **Invalid keys** cost a database read each and have no limit of their own. [ARCH: 9. Rate limiting] [ASSUMPTION AA-14]

## 9. Security

- **Who may call:** signup and login are public; refresh needs the cookie; key management needs a browser login; everything else needs an API key. [ARCH: 8. Authentication and authorisation]
- **Isolation:** every query is scoped by the organisation of the credential. [ARCH: 8. Authentication and authorisation]
- **Secrets:** passwords use Argon2; keys use SHA-256 because they are long and random. Keys and passwords are never stored in plain text or logged. [DB: api_keys.key_hash] [ARCH: 16. Security notes] [NOTEPAD: D34]
- **Token handling:** the access token lives in browser memory, and the refresh cookie is httpOnly, Secure and `SameSite=Strict` on the refresh path. Script injection into the page could read the access token. [ARCH: 8. Authentication and authorisation] [ARCH: 16. Security notes] [ASSUMPTION AA-15]
- **Deployment rule:** frontend and API must be on the same site for the cookie to work. [ARCH: 8. Authentication and authorisation]
- **JWT algorithm and key handling** are not stated beyond a signing secret, issuer and audience; asymmetric signing is deferred. [ARCH: 8. Authentication and authorisation] [DEFERRED: asymmetric JWT signing and a key id] [ASSUMPTION AA-06]
- **Signup without verification** lets anyone register an address that is not theirs and block its owner, and with no password reset a forgotten password locks the account out. [ARCH: 19. Known risks] [DEFERRED: account recovery]
- **OAuth rule for later:** never link an OAuth login to an existing user by unverified email. [ARCH: 8. Authentication and authorisation]
- **Roles:** the three roles exist but their permissions are not listed. [DB: memberships.role] [ASSUMPTION AA-05]

## 10. Open questions and deferred items

- Email verification and the email sender; password reset and invitations; account recovery. [DEFERRED: email verification and the email sender] [DEFERRED: password reset and member invitations] [DEFERRED: account recovery]
- Idle session limit; access-token denylist; password re-entry before key actions; token-based CSRF; asymmetric signing; OAuth providers. [DEFERRED: idle session timeout] [DEFERRED: access-token denylist] [DEFERRED: password re-entry before creating or revoking an API key] [DEFERRED: token-based CSRF protection]
- Trusted-proxy setting and per-email login limit. [DEFERRED: trusted-proxy setting and per-email login limit]
- Whether the access token needs organisation switching. [NOTEPAD: 10. Open items]
- Open details: organisation name and slug at signup, password rules, role permissions, status codes, response shapes, what happens with a suspended organisation or disabled user. [ASSUMPTION AA-01] [ASSUMPTION AA-02] [ASSUMPTION AA-05] [ASSUMPTION AA-12]
