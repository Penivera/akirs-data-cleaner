# Changelog

All notable changes to the AKIRS Data Toolkit are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] - 2026-09-21

### Added
- **Self-service signup** (`POST /api/auth/signup`): collects email, password, and
  full name. New accounts are created with `is_approved = False` and cannot sign in
  until an administrator approves them.
- **Admin approval workflow**: the Starlette Admin Users view gains bulk
  **Approve**, **Reject / disable**, and **Reset 2FA** actions plus an
  `is_approved` filter. Approve/Reject/Reset are themselves written to the audit
  log with the acting administrator recorded.
- **Mandatory TOTP two-factor authentication** (`app/core/mfa.py`):
  - `POST /api/auth/2fa/setup` — returns a secret, the `otpauth://` provisioning
    URI, and `qr_svg` (a scannable SVG QR code data URI rendered with `segno`).
  - `POST /api/auth/2fa/enable` — verifies a code and issues 10 one-time recovery codes.
  - `POST /api/auth/2fa/verify` — completes login with a TOTP code or a recovery code.
  - Recovery codes are stored hashed and consumed once.
  - All logins now return an MFA challenge instead of tokens; tokens are only issued
    after the second factor is satisfied. Users without 2FA are forced to set it up
    on first login.
- **`segno` dependency** for server-side QR generation (zero-dependency, no Pillow).
- **New models/fields**: `User.is_approved`, `User.totp_secret`,
  `User.pending_totp_secret`, `User.totp_enabled`, and the `RecoveryCode` table.
- **Additive migration** (`app/core/database.py`): `init_db()` adds the new user
  columns to databases created before this change.
- **`tzdata` dependency** so Starlette Admin datetime rendering works on Windows.
- New config: `TOTP_ISSUER`, `MFA_CHALLENGE_EXPIRE_MINUTES`, `RECOVERY_CODE_COUNT`.

### Changed
- `POST /api/auth/login` now returns `MfaChallengeResponse`
  (`mfa_required` / `setup_required` / `challenge_token`) and no longer returns
  tokens directly. A 403 is returned for pending (`Account pending administrator
  approval`) or disabled accounts.
- `UserOut` now includes `is_approved` and `totp_enabled`.
- Superuser seeded by the bootstrap is created with `is_approved = True`.
- `requirements.txt` adds `pyotp==2.10.0`, `segno==1.6.6`, and `tzdata==2026.4`.

### Frontend (cookie-free auth UI)
- **Shared auth core** (`static/js/auth-core.js`): token storage
  (`localStorage`), MFA challenge (`sessionStorage`), silent refresh, `apiFetch`,
  authenticated `download`/`view`/batch-zip helpers, HTMX `Authorization`
  injection, and 401 handling.
- **Account flow** (`static/js/auth.js`, `templates/auth.html`): login → MFA
  challenge routing, signup with pending-approval state, authenticator setup
  (scannable QR + manual setup key + code), TOTP/recovery-code verification, and
  one-time recovery-code display.
- **Workspace shell** (`/app`, `static/js/session.js`): public, data-free shell
  that guards on the stored token and loads content over HTMX with the bearer
  token. `/` still redirects unauthenticated browser navigation to `/auth`.
- **Authenticated downloads**: all download/report links and the batch ZIP now go
  through `AKIRSAuth` (fetch + blob) instead of plain `<a href>`.
- `/auth/recovery` route added; account pages remain public.

## [0.2.0] - 2026-09-21

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
- **Frontend integration.** Implemented in the `[Unreleased]` section above
  (account pages, mandatory-2FA UI, `/app` shell, authenticated downloads). See
  `docs/frontend-integration.md` and `docs/auth-pages.md`.
