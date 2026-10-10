# frontend

Part 1 of 14. Draft for review. Tags are explained in [overview.md](overview.md) section 0.

The sources say little about the frontend, so this file has more assumptions than the others.

## 1. Purpose and non-responsibilities

**Purpose.** A minimal Next.js app, in its own container, for signup, login, and managing API keys (list, create, revoke). It keeps the access token in browser memory and runs the token refresh. [NOTEPAD: D9] [ARCH: 2. Goals and non-goals] [ARCH: 8. Authentication and authorisation]

**Does not do:**
- Show or manage jobs, files or results. The browser login cannot call the job APIs, and a full admin console is a non-goal. [ARCH: 8. Authentication and authorisation] [ARCH: 2. Goals and non-goals]
- Verify email, reset passwords, invite members or log in with OAuth providers. [DEFERRED: email verification and the email sender] [DEFERRED: password reset and member invitations] [DEFERRED: OAuth login providers]
- Switch organisations. [NOTEPAD: 10. Open items]
- Stream live progress. [NOTEPAD: D11]

## 2. Interfaces provided

### 2.1 `pages` (used by people, not by other parts)

| Page | What it does | Source |
|---|---|---|
| Signup | Calls [accounts-auth#signup] | [NOTEPAD: D9] |
| Login | Calls [accounts-auth#login] | [NOTEPAD: D9] |
| API keys list | Calls [accounts-auth#list-api-keys]; shows name, prefix, scopes, expiry, revoked state and last use | [NOTEPAD: D9] [DB: api_keys] |
| Create key | Calls [accounts-auth#create-api-key]; shows the full key once | [NOTEPAD: D9] [ARCH: 8. Authentication and authorisation] |
| Revoke key | Calls [accounts-auth#revoke-api-key] | [NOTEPAD: D9] |
| Logout | Calls [accounts-auth#logout] | [ARCH: 8. Authentication and authorisation] |

Page layout, fields and wording are not specified. [ASSUMPTION FE-06]

### 2.2 `token-refresh-coordinator` (inside the app)

| Rule | Detail | Source |
|---|---|---|
| One refresher | Only one browser tab refreshes at a time | [ARCH: 8. Authentication and authorisation] |
| Retry once | On the "already refreshed" error, retry once with the cookie the browser now holds | [ARCH: 8. Authentication and authorisation] |
| Memory only | The access token lives in browser memory | [ARCH: 8. Authentication and authorisation] |
| First load | A page reload needs a refresh before the first authenticated call | [ASSUMPTION A-06] |
| Mechanism | How tabs coordinate (for example a shared lock or a broadcast channel) is not stated | [ASSUMPTION FE-02] |

## 3. Interfaces consumed

| From | Interface | How it is used |
|---|---|---|
| `accounts-auth` | [accounts-auth#signup], [accounts-auth#login], [accounts-auth#refresh], [accounts-auth#logout], [accounts-auth#create-api-key], [accounts-auth#list-api-keys], [accounts-auth#revoke-api-key] | Every action above. The access token goes in `Authorization: Bearer`; the refresh cookie is sent by the browser to the refresh path |

Sources: [ARCH: 8. Authentication and authorisation] [ARCH: 14. API documentation rules]

The browser reaches the API on the same site as the frontend, either directly or through the Next.js server proxying API calls on its own origin. Which one is used is not decided. [ARCH: 8. Authentication and authorisation] [ASSUMPTION FE-09]

## 4. Data

**Server-side data:** none of its own. [NOTEPAD: D9]

**In the browser:** the access token in memory; the refresh token in an httpOnly cookie that scripts cannot read. [ARCH: 8. Authentication and authorisation] Use of local storage or session storage is not described. [ASSUMPTION FE-05]

**Who else touches them:** the refresh cookie is set and read by the API's refresh and logout endpoints. [ARCH: 8. Authentication and authorisation]

## 5. Internal workflow

1. **Signup / login:** submit the form to `accounts-auth`; on success keep the access token in memory. [ARCH: 8. Authentication and authorisation] Whether signup also logs in is not stated. [ASSUMPTION AA-03]
2. **Staying logged in:** refresh before the access token expires (about 15 minutes) and when the API answers that it is expired. [ARCH: 8. Authentication and authorisation] [ASSUMPTION FE-02]
3. **Page reload:** call refresh first to get a new access token. [ASSUMPTION A-06]
4. **Create key:** send the request, show the full key once, and tell the user it cannot be shown again. [ARCH: 8. Authentication and authorisation]
5. **List and revoke keys:** call the list and revoke endpoints; a revoked key takes effect on its next request. [DB: api_keys.revoked_at]
6. **Logout:** call logout and drop the token from memory; the old access token stays valid until it expires. [ARCH: 8. Authentication and authorisation]
7. **Rendering model:** because the token is only in browser memory, authenticated pages must fetch data in the browser; whether any page is rendered on the Next.js server is not stated. [ARCH: 8. Authentication and authorisation] [ASSUMPTION FE-01]

## 6. Failure modes

| Step | If it fails | State left behind | Source |
|---|---|---|---|
| Refresh returns "already refreshed" | Retry once with the cookie now held | None | [ARCH: 8. Authentication and authorisation] |
| Refresh returns unauthenticated (revoked family, reuse after the window, expired family) | The user must log in again; what the app does with unsaved input is not stated | Token dropped | [ARCH: 8. Authentication and authorisation] [DB: refresh_tokens.family_expires_at] [ASSUMPTION FE-03] |
| Network error during create key | The user does not know whether a key exists; retrying creates a second one | Possibly an unseen key | [DB: api_keys] [ASSUMPTION FE-04] |
| User leaves the page after create key | The full key is lost; it was shown once and only a hash is stored | A key nobody can use | [ARCH: 8. Authentication and authorisation] |
| API rate limited (429) | How the app shows it is not stated | None | [ARCH: 9. Rate limiting] [ASSUMPTION FE-07] |
| Redis down | Login and signup are rejected; refresh keeps working | Logged-in users keep working | [ARCH: 9. Rate limiting] |
| Frontend and API on different sites | The refresh cookie is not sent, so login does not persist | Broken login | [ARCH: 8. Authentication and authorisation] |
| Cookies blocked | Refresh cannot work | Broken login | [ASSUMPTION FE-03] |

## 7. Concurrency and idempotency

- Several tabs: one refreshes while the others wait for the result. [ARCH: 8. Authentication and authorisation]
- Creating a key is not idempotent; a double click or a retry makes two keys. [DB: api_keys] [ASSUMPTION FE-04]
- Logout in one tab revokes the whole family, so every tab loses its login on its next refresh. [ARCH: 8. Authentication and authorisation]

## 8. Performance notes

Load assumptions are in [overview.md](overview.md) section 8. [ASSUMPTION L-04]

- **Refresh traffic** grows with page loads, not logins: each reload costs one refresh, a database rotation and a new row in `refresh_tokens`. At 5,000 users loading a few pages a day this is small. [DB: refresh_tokens] [ASSUMPTION A-06] [ASSUMPTION L-04]
- **No polling** and no job views, so no read load from this part. [ARCH: 2. Goals and non-goals]
- **Bundle and rendering** costs are not discussed. [ASSUMPTION FE-01]

## 9. Security

- **Token exposure:** the access token in page memory can be read by script injected into the page; the refresh cookie cannot. Content-security headers and other XSS defences are not described. [ARCH: 8. Authentication and authorisation] [ARCH: 16. Security notes] [ASSUMPTION FE-05]
- **CSRF:** `SameSite` cookies plus an origin check on state-changing requests; token-based CSRF is deferred. [ARCH: 16. Security notes] [DEFERRED: token-based CSRF protection]
- **CORS:** an explicit allowlist. [ARCH: 16. Security notes]
- **Same-site rule:** `SameSite=Strict` needs frontend and API on one site. [ARCH: 8. Authentication and authorisation]
- **Keys:** the full key is shown once and never stored by the app. [ARCH: 8. Authentication and authorisation]
- **No verification at signup**, so the form accepts any email address. [ARCH: 8. Authentication and authorisation]
- Scaffolding must come from the framework generator, and versions (including TypeScript 7 with Next.js 16.4) are not yet verified. [NOTEPAD: Phase 0 verification results]

## 10. Open questions and deferred items

- Organisation switching when a user belongs to several. [NOTEPAD: 10. Open items]
- Password reset, email verification, OAuth, idle session limit, password re-entry before key actions. [DEFERRED: password reset and member invitations] [DEFERRED: email verification and the email sender] [DEFERRED: OAuth login providers] [DEFERRED: idle session timeout] [DEFERRED: password re-entry before creating or revoking an API key]
- Rendering model, tab coordination, direct versus proxied API calls, error and rate-limit display, and what happens to unsaved input on forced login. [ASSUMPTION FE-01] [ASSUMPTION FE-02] [ASSUMPTION FE-03] [ASSUMPTION FE-07] [ASSUMPTION FE-09]
