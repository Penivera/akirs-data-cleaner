# Changelog

All notable changes to the AKIRS Data Toolkit are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] - 2026-09-21

### Added
- **Database layer** (`app/core/database.py`): SQLAlchemy 2.0 engine, `SessionLocal`,
  declarative `Base`, and `init_db()`. Defaults to SQLite at `data/app.db`; switchable
  to PostgreSQL via `DATABASE_URL`.
- **ORM models** (`app/core/models.py`):
  - `User` — email, hashed password, active/superuser flags, `token_version`
    (for global token revocation), timestamps.
  - `RefreshToken` — hashed refresh token records for rotation and revocation.
  - `AuditLog` — action, user, filename, status, detail, IP, timestamp.
- **Security helpers** (`app/core/security.py`): bcrypt password hashing plus
  PyJWT access/refresh token creation, decoding, and hashing.
- **Auth dependencies** (`app/core/deps.py`): `get_db`, `get_current_user`
  (Bearer JWT, validates `token_version`), and `get_current_superuser`.
- **Auth API** (`app/api/auth.py`): `POST /api/auth/login`, `POST /api/auth/refresh`
  (with rotation), `POST /api/auth/logout`, `GET /api/auth/me`.
- **Audit logging** (`app/services/audit.py`) wired into every upload, process,
  resolve, generate, sync, delete, and download handler across the four routers.
- **Starlette Admin** (`app/admin/`): dashboard mounted at `/admin` with a
  superuser-only session auth provider, a `UserView` (create/edit users with
  automatic password hashing), and a read-only, searchable `AuditLogView`.
- **Superuser bootstrap**: seeded on first startup from `ADMIN_EMAIL` /
  `ADMIN_PASSWORD`; a random password is generated and logged once if unset.
- **Configuration**: `SECRET_KEY`, `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
  `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`,
  `ADMIN_SESSION_MAX_AGE`, `ADMIN_SESSION_HTTPS_ONLY`.
- **Docs**: `docs/auth-api.md` (endpoint reference) and
  `docs/frontend-integration.md` (frontend guide).

### Changed
- `main.py` now calls `init_db()` and `seed_superuser()` on startup, installs
  `SessionMiddleware` for the admin UI, mounts the auth router publicly, and
  applies `Depends(get_current_user)` to all existing routers.
- All existing application routes now require a valid `Authorization: Bearer`
  token. Static assets, `/docs`, `/openapi.json`, `/api/auth/login`, and
  `/api/auth/refresh` remain public.
- `requirements.txt` adds `SQLAlchemy==2.0.54`, `starlette-admin==1.0.1`,
  `bcrypt==5.0.0`, `PyJWT==2.14.0`, `itsdangerous==2.2.0`.
- `.gitignore` ignores the local `data/` database directory and `*.db` files.
- `README.md` gains an "Authentication & Admin" section.

### Security
- Stateless JWT access tokens (default 30 min) with refresh-token rotation
  (default 7 days). Reusing a rotated refresh token is rejected.
- `logout` revokes a single refresh token, or all of them (`all_devices`), by
  bumping the user's `token_version` and invalidating outstanding access tokens.
- Startup logs a warning when `SECRET_KEY` is missing, default, or under 32 bytes.

### Not included (pending)
- **Frontend integration.** The login page, token storage, HTMX `Authorization`
  header injection, 401/refresh handling, and authenticated downloads are not yet
  implemented. See `docs/frontend-integration.md`. Until then, browser navigation
  to `/` returns `401`.
