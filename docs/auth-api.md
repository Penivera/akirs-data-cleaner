# Authentication & Admin API Reference

> Browser integration: `/auth` now provides account pages, and successful login
> also sets an HttpOnly access cookie for workspace navigation. Bearer tokens
> remain supported. See [Account pages](auth-pages.md) for the supported flow,
> session behavior and the signup/MFA backend features that are still unavailable.

> Added 2026-09-21. Covers JWT authentication and the Starlette Admin dashboard.

## Overview

| Area | Mechanism | Auth |
|------|-----------|------|
| Application API/UI | Stateless JWT in `Authorization: Bearer <token>` | `get_current_user` dependency |
| Admin UI (`/admin`) | Session cookie (starlette-admin), superusers only | `AdminAuthProvider` |
| Storage | SQLAlchemy — SQLite (`data/app.db`) by default | — |

**Public paths** (no token required): `/api/auth/login`, `/api/auth/refresh`,
`/static/*`, `/docs`, `/redoc`, `/openapi.json`, `/admin/*` (has its own login).

**Everything else requires** a valid access token. A missing, malformed,
expired, revoked, or version-mismatched token returns `401`.

---

## Token model

- **Access token** — JWT, default lifetime 30 min (`ACCESS_TOKEN_EXPIRE_MINUTES`).
  Claims: `sub` (user id), `type="access"`, `jti`, `ver` (user `token_version`),
  `iat`, `exp`.
- **Refresh token** — JWT, default lifetime 7 days (`REFRESH_TOKEN_EXPIRE_DAYS`).
  Claims: `sub`, `type="refresh"`, `jti`, `ver`, `iat`, `exp`. Persisted hashed
  in `refresh_tokens` for rotation/revocation.
- Refresh is **rotating**: each successful refresh revokes the old refresh token
  and issues a new access + refresh pair. Reusing a spent token returns `401`.
- Bumping a user's `token_version` (via logout-all or admin) invalidates every
  access and refresh token previously issued to that user.

Send the token on every protected request:

```
Authorization: Bearer <access_token>
```

---

## Data shapes

### `UserOut`

```json
{
  "id": 1,
  "email": "admin@akirs.local",
  "full_name": "Administrator",
  "is_active": true,
  "is_superuser": true,
  "created_at": "2026-09-21T10:00:00Z",
  "last_login": "2026-09-21T12:30:00Z"
}
```

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

`expires_in` is the access-token lifetime in seconds.

---

## Endpoints

### `POST /api/auth/login`

Authenticate with email and password.

**Auth:** none

**Request body**

```json
{ "email": "admin@akirs.local", "password": "your-password" }
```

**Responses**

| Status | Meaning | Body |
|--------|---------|------|
| `200` | Success | `TokenResponse` |
| `401` | Invalid email or password | `{ "detail": "Invalid email or password" }` |
| `403` | Account disabled | `{ "detail": "Account is disabled" }` |
| `422` | Validation error (missing/blank/invalid email) | FastAPI validation detail |

**Notes:** email is trimmed and lower-cased before lookup. A successful login
updates `last_login` and writes a `login` audit entry.

---

### `POST /api/auth/refresh`

Exchange a refresh token for a new token pair.

**Auth:** none (the refresh token itself is the credential)

**Request body**

```json
{ "refresh_token": "eyJhbGciOiJIUzI1NiIs..." }
```

**Responses**

| Status | Meaning |
|--------|---------|
| `200` | New `TokenResponse` (old refresh token is now revoked) |
| `401` | Invalid / expired / revoked / reused refresh token |

**Notes:** rotation is enforced. Persist the new `refresh_token` and discard the
old one; the old one will not work again.

---

### `POST /api/auth/logout`

Revoke refresh token(s) for the authenticated user.

**Auth:** `Authorization: Bearer <access_token>`

**Request body**

```json
{ "refresh_token": "optional-current-refresh-token", "all_devices": false }
```

- `refresh_token` — if provided, that specific token is revoked.
- `all_devices: true` — revokes **all** of the user's refresh tokens and bumps
  `token_version`, invalidating every outstanding access token too.

**Responses**

| Status | Meaning |
|--------|---------|
| `204` | Revoked (no body) |
| `401` | Missing/invalid access token |

---

### `GET /api/auth/me`

Return the current user profile.

**Auth:** `Authorization: Bearer <access_token>`

**Responses**

| Status | Meaning | Body |
|--------|---------|------|
| `200` | Current user | `UserOut` |
| `401` | Missing/invalid token | `{ "detail": "Could not validate credentials" }` |

---

## Admin dashboard

**Base URL:** `/admin`
**Auth:** starlette-admin session cookie; only users with
`is_superuser = true` and `is_active = true` can sign in.

- Login form at `/admin/login`.
- **Users** view — create/edit/deactivate accounts. The password field is hashed
  automatically; leave it blank when editing to keep the current password.
  Increment `token_version` to force-revoke all of a user's tokens.
- **Audit log** view — read-only, searchable history of uploads, processing,
  downloads, syncs, deletes, logins, and logouts.

The session cookie (`akirs_admin_session`) is issued only when using `/admin`.
The application itself never reads it.

---

## Protected application endpoints

All of the following now require `Authorization: Bearer <access_token>`.
See `docs/system-design.md` for behavior; this list is the auth-relevant surface.

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

The superuser is seeded **only when the users table is empty**. Delete
`data/app.db` to re-seed after changing `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

---

## Quick reference (curl)

```bash
# login
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@akirs.local","password":"your-password"}'

# authenticated call
curl -s http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <access_token>"

# refresh
curl -s -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'

# logout (single token)
curl -s -X POST http://localhost:8000/api/auth/logout \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
```
