# Authentication & Admin API Reference

> Updated 2026-09-21. Covers JWT authentication, self-service signup, admin
> approval, mandatory TOTP two-factor authentication, and the Starlette Admin
> dashboard.

> Public account pages are served at `/auth` (and `/auth/setup`, `/auth/verify`,
> `/auth/mfa`, `/auth/pending`); see [Account pages](auth-pages.md). The browser
> flow is being updated for mandatory 2FA — login now returns an MFA challenge
> rather than tokens, and the app is Bearer-only (no auth cookie).

## Overview

| Area | Mechanism | Auth |
|------|-----------|------|
| Application API/UI | Stateless JWT in `Authorization: Bearer <token>` | `get_current_user` dependency |
| Signup | `POST /api/auth/signup` → pending admin approval | none |
| Login | Password → MFA challenge → TOTP/recovery code → tokens | none until tokens issued |
| Admin UI (`/admin`) | Session cookie (starlette-admin), superusers only | `AdminAuthProvider` |
| Storage | SQLAlchemy — SQLite (`data/app.db`) by default | — |

**Public paths** (no token required): `/api/auth/signup`, `/api/auth/login`,
`/api/auth/2fa/setup`, `/api/auth/2fa/enable`, `/api/auth/2fa/verify`,
`/api/auth/refresh`, `/static/*`, `/docs`, `/redoc`, `/openapi.json`,
`/admin/*` (has its own login).

**Everything else requires** a valid access token. A missing, malformed,
expired, revoked, or version-mismatched token returns `401`.

### Account lifecycle

```
signup ──▶ pending approval ──▶ (admin approves) ──▶ active
                                                      │
                                    login (password) ─┤
                                                      ▼
                              MFA setup (first login) ──▶ enable ──▶ tokens
                                                      │
                              later logins: TOTP code or recovery code ──▶ tokens
```

- New accounts are created `is_approved = false` and cannot log in.
- An administrator approves/rejects them from `/admin` (or via the actions API).
- 2FA is **mandatory**: after approval, the first login forces TOTP setup;
  subsequent logins require a TOTP (or one-time recovery) code.

---

## Token model

- **Access token** — JWT, default lifetime 30 min (`ACCESS_TOKEN_EXPIRE_MINUTES`).
  Claims: `sub`, `type="access"`, `jti`, `ver`, `iat`, `exp`.
- **Refresh token** — JWT, default lifetime 7 days (`REFRESH_TOKEN_EXPIRE_DAYS`).
  Persisted hashed in `refresh_tokens`; rotating.
- **MFA challenge token** — short-lived JWT (default 10 min,
  `MFA_CHALLENGE_EXPIRE_MINUTES`) with `type="mfa"` (verify) or
  `type="mfa_setup"` (setup). Issued by login; exchanged for tokens.

Bumping a user's `token_version` (logout-all, reject, reset-2FA) invalidates every
access, refresh, and challenge token previously issued.

Send the access token on protected requests:

```
Authorization: Bearer <access_token>
```

---

## Data shapes

### `UserOut`

```json
{
  "id": 2,
  "email": "user1@akirs.local",
  "full_name": "User One",
  "is_active": true,
  "is_approved": true,
  "is_superuser": false,
  "totp_enabled": true,
  "created_at": "2026-09-21T10:00:00Z",
  "last_login": "2026-09-21T12:30:00Z"
}
```

### `MfaChallengeResponse` (login result)

```json
{
  "mfa_required": false,
  "setup_required": true,
  "challenge_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

- `setup_required: true` — user has not configured 2FA yet; call `/2fa/setup`.
- `mfa_required: true` — user has 2FA; call `/2fa/verify`.

### `TokenResponse`

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": { "...UserOut..." }
}
```

`MfaTokenResponse` is the same plus `recovery_codes` (only populated by
`/2fa/enable`).

---

## Endpoints

### `POST /api/auth/signup`

Create an account pending administrator approval.

**Auth:** none

**Request body**

```json
{ "email": "user@akirs.local", "password": "at-least-8-chars", "full_name": "Jane Doe" }
```

**Responses**

| Status | Meaning |
|--------|---------|
| `201` | `{ "detail": "...pending approval...", "user_id": 2 }` |
| `409` | Email already registered |
| `422` | Validation error (invalid email, password < 8 chars) |

---

### `POST /api/auth/login`

Verify credentials and return an MFA challenge. **Never returns tokens directly.**

**Auth:** none

**Request body**

```json
{ "email": "user@akirs.local", "password": "..." }
```

**Responses**

| Status | Meaning | Body |
|--------|---------|------|
| `200` | Challenge issued | `MfaChallengeResponse` |
| `401` | Invalid email or password | `{ "detail": "Invalid email or password" }` |
| `403` | Account disabled | `{ "detail": "Account is disabled" }` |
| `403` | Not yet approved | `{ "detail": "Account pending administrator approval" }` |

---

### `POST /api/auth/2fa/setup`

Start TOTP setup for a user in the `mfa_setup` challenge state.

**Auth:** none (requires `challenge_token` from login)

**Request body**

```json
{ "challenge_token": "eyJhbGciOiJIUzI1NiIs..." }
```

**Response `200`**

```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "otpauth_url": "otpauth://totp/AKIRS%20Data%20Toolkit:user@akirs.local?secret=...&issuer=AKIRS%20Data%20Toolkit",
  "qr_svg": "data:image/svg+xml;charset=utf-8,%3Csvg..."
}
```

`qr_svg` is a ready-to-use SVG data URI — put it straight into an `<img src>` so
the user can **scan the QR code** with an authenticator app. `secret` and
`otpauth_url` remain available for manual entry. The secret is stored server-side
as `pending_totp_secret` until enabled.

---

### `POST /api/auth/2fa/enable`

Confirm setup with a code, enable 2FA, and receive tokens plus recovery codes.

**Auth:** none (requires `challenge_token` from login)

**Request body**

```json
{ "challenge_token": "eyJhbGciOiJIUzI1NiIs...", "code": "123456" }
```

**Responses**

| Status | Meaning |
|--------|---------|
| `200` | `MfaTokenResponse` with `recovery_codes` (10 codes, shown once) |
| `400` | Invalid verification code, or setup not started |

Store the recovery codes securely; they are hashed server-side and cannot be
retrieved again.

---

### `POST /api/auth/2fa/verify`

Complete login with a TOTP code or a one-time recovery code.

**Auth:** none (requires `challenge_token` from login)

**Request body**

```json
{ "challenge_token": "eyJhbGciOiJIUzI1NiIs...", "code": "123456" }
```

or

```json
{ "challenge_token": "eyJhbGciOiJIUzI1NiIs...", "recovery_code": "a1b2c-3d4e5" }
```

**Responses**

| Status | Meaning |
|--------|---------|
| `200` | `MfaTokenResponse` (no recovery codes) |
| `400` | Invalid code / recovery code already used / 2FA not configured |
| `401` | Invalid or expired challenge token |

Recovery codes are single-use; reusing one returns `400`.

---

### `POST /api/auth/refresh`

Exchange a refresh token for a new token pair. (Unchanged.)

**Auth:** none

**Request body:** `{ "refresh_token": "..." }`

| Status | Meaning |
|--------|---------|
| `200` | New `TokenResponse` (old refresh token revoked) |
| `401` | Invalid / expired / revoked / reused refresh token |

---

### `POST /api/auth/logout`

**Auth:** `Authorization: Bearer <access_token>`

**Request body:** `{ "refresh_token": "...", "all_devices": false }`

`all_devices: true` revokes all refresh tokens and bumps `token_version`.
Returns `204`.

---

### `GET /api/auth/me`

**Auth:** `Authorization: Bearer <access_token>` → `UserOut`.

---

## Admin dashboard

**Base URL:** `/admin` · **Auth:** session cookie, active superusers only.

- **Users** view — create/edit/deactivate accounts; `is_approved` toggle; filters
  (including `is_approved`, `is_superuser`, `totp_enabled`). Bulk actions:
  - **Approve selected** — sets `is_approved = true`, `is_active = true`.
  - **Reject / disable selected** — sets both false and bumps `token_version`.
  - **Reset 2FA** — clears the TOTP secret and recovery codes and bumps
    `token_version`, forcing the user to set up 2FA again.
- **Audit log** view — read-only, searchable/filterable history of actions by
  **all users**, including `signup`, `login`, `2fa_*`, uploads, processing,
  downloads, syncs, deletes, and admin actions (`user_approved`, `user_rejected`,
  `user_2fa_reset`). Each row shows the acting `user_email`.

---

## Protected application endpoints

All of the following require `Authorization: Bearer <access_token>`.

| Router | Endpoints |
|--------|-----------|
| `routes.py` | `GET /`, `POST /api/upload`, `POST /api/components/mapping/{file_id}`, `POST /api/mapping/{file_id}`, `DELETE /api/delete/{file_id}`, `POST /api/process/{file_id}`, `POST /api/duplicates/{file_id}`, `POST /api/db-resolve/{file_id}`, `GET /api/view/process`, `GET /api/view/cleaned`, `GET /api/view/{file_id}`, `GET /api/view-skipped/{file_id}`, `GET /api/download/{filename}`, `POST /api/download-batch` |
| `analytics.py` | `GET /api/analyse/view`, `POST /api/analyse/upload`, `POST /api/analyse/config/{file_id}`, `POST /api/analyse/components/config-form/{file_id}`, `POST /api/analyse/generate/{file_id}`, `DELETE /api/analyse/delete/{file_id}`, `GET /api/analyse/download/{filename}`, `GET /api/analyse/view-report/{filename}` |
| `nuban.py` | `GET /api/nuban/view`, `POST /api/nuban/upload`, `POST /api/nuban/config-form/{file_id}`, `POST /api/nuban/save-config/{file_id}`, `POST /api/nuban/resolve/{file_id}`, `DELETE /api/nuban/delete/{file_id}` |
| `intelligence.py` | `GET /api/intel/view`, `POST /api/intel/upload`, `POST /api/intel/config-form/{file_id}`, `POST /api/intel/save-config/{file_id}`, `DELETE /api/intel/delete/{file_id}` |

---

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | `change-me-in-production` | Signs JWTs and admin sessions. **Set a 32+ byte random value.** |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLAlchemy URL (PostgreSQL supported). |
| `ADMIN_EMAIL` | `admin@akirs.local` | Seeded superuser email. |
| `ADMIN_PASSWORD` | *(none)* | Seeded superuser password; random + logged if unset. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime. |
| `ADMIN_SESSION_MAX_AGE` | `1209600` | Admin cookie lifetime (seconds). |
| `ADMIN_SESSION_HTTPS_ONLY` | `false` | Mark admin cookie HTTPS-only. |
| `TOTP_ISSUER` | `AKIRS Data Toolkit` | Issuer shown in authenticator apps. |
| `MFA_CHALLENGE_EXPIRE_MINUTES` | `10` | MFA challenge token lifetime. |
| `RECOVERY_CODE_COUNT` | `10` | Recovery codes issued on 2FA enable. |

The superuser is seeded **only when the users table is empty**. Delete
`data/app.db` to re-seed after changing `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

---

## Quick reference (curl)

```bash
# signup
curl -s -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"user@akirs.local","password":"UserPass123!","full_name":"User One"}'

# login -> challenge
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@akirs.local","password":"UserPass123!"}'

# (first login) start 2FA setup
curl -s -X POST http://localhost:8000/api/auth/2fa/setup \
  -H "Content-Type: application/json" \
  -d '{"challenge_token":"<challenge_token>"}'

# (first login) enable 2FA with the code from the authenticator app
curl -s -X POST http://localhost:8000/api/auth/2fa/enable \
  -H "Content-Type: application/json" \
  -d '{"challenge_token":"<challenge_token>","code":"123456"}'

# (later logins) verify
curl -s -X POST http://localhost:8000/api/auth/2fa/verify \
  -H "Content-Type: application/json" \
  -d '{"challenge_token":"<challenge_token>","code":"123456"}'

# authenticated call
curl -s http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <access_token>"
```
