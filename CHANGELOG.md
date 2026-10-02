# Changelog

All notable changes to the AKIRS Data Toolkit are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-10-02

Production-hardening release: per-user data isolation, automatic cleanup,
database-backed state for multi-worker deployments, and upload/processing
performance work.

### Added

#### User data isolation
- `user_id` on `FileState`, `AnalysisState`, `NubanState`, and `IntelSyncState`.
- Per-user storage directories created on demand:
  `get_user_upload_dir()` → `uploads/{user_id}/`,
  `get_user_cleaned_dir()` → `cleaned/{user_id}/`,
  `get_user_reports_dir()` → `reports/{user_id}/` (`app/core/state.py`).
- Every list/upload/process/resolve/delete/view/download endpoint now filters by
  `current_user.id`; a file owned by another user reads as "File not found".
- Downloads and the batch ZIP are resolved inside the caller's own directories
  (`/api/download/{filename}`, `/api/analyse/download/{filename}`,
  `/api/analyse/view-report/{filename}`, `/api/download-batch`).

#### Upload validation (`app/services/validators.py`)
- `validate_upload()` enforces an extension allow-list (`.xlsx`, `.xls`, `.csv`)
  and rejects oversized uploads with HTTP 413 before the body is read.
- New settings: `MAX_UPLOAD_SIZE_MB` (default 50), `ALLOWED_EXTENSIONS`.

#### Automatic cleanup (`app/services/cleanup.py`)
- `cleanup_stale_files()` deletes files older than `CLEANUP_MAX_AGE_HOURS`
  (default 24) from `uploads/`, `cleaned/`, and `reports/`, removes empty
  per-user directories, and purges expired work-item/task rows.
- Scheduled with APScheduler: runs once at startup and then every
  `CLEANUP_INTERVAL_HOURS` (default 24) via the FastAPI lifespan.
- New settings: `CLEANUP_ENABLED` (default true), `CLEANUP_MAX_AGE_HOURS`,
  `CLEANUP_INTERVAL_HOURS`; `APScheduler` added as a dependency.

#### Database-backed state (multi-worker)
- New tables `work_items` (JSON blob plus indexed `kind`, `user_id`,
  `uploaded_at`, `status`) and `tasks` (`app/core/models.py`).
- New repository module `app/core/repository.py`:
  `put` / `get` / `list_for_user` / `delete`, task helpers
  (`set_task`, `update_task`, `get_task`), and `purge_older_than`.
  State objects are serialized to JSON (`state.__dict__`) and reconstructed
  into their original class.
- SQLite engine now enables `journal_mode=WAL`, `busy_timeout=5000`,
  `synchronous=NORMAL`, and `foreign_keys=ON` (`app/core/database.py`).
- This replaces the in-memory dictionaries and `uploads/state_database.pkl`
  pickle, so every Gunicorn worker sees the same state.

#### Processing performance
- `app/core/executor.py`: a dedicated, bounded `ThreadPoolExecutor` with an
  async `run_cpu()` helper. All CPU-bound work (Excel/CSV parsing, record
  extraction, duplicate detection, CSV writing) runs off the event loop without
  starving FastAPI's synchronous-dependency pool. New setting
  `PROCESSING_THREADS` (default 2).
- Uploads stream to disk in 1 MB chunks with the size cap enforced mid-stream,
  so memory use stays flat regardless of file size.
- File processing runs as a FastAPI background task: the request returns
  immediately with a `Processing...` status; a new
  `GET /api/task-status/{task_id}` endpoint is polled by the UI
  (`static/js/app.js`, `templates/partials/file_card.html`) until completion.

#### Authentication
- `MfaChallengeResponse` now includes `recovery_codes_available`, so the UI can
  hide the recovery-code path when a user has none.

#### Tests
- `test_user_data_isolation` — a file owned by one user is invisible and
  inaccessible to another, and cannot be deleted by them.
- `test_repository_roundtrip_tasks_and_purge` — JSON round-trip of nested state
  (mapped-field lists, records, duplicate groups, health report), background
  task lifecycle, and the purge job.

### Changed
- `state.py` no longer holds global dictionaries; persistence is delegated to the
  repository. `main.py` starts the cleanup scheduler and shuts down the CPU pool
  in its lifespan.
- `save_cleaned_records()` and the analyser report functions accept an
  `output_dir`; `process_nuban_resolution()` writes to the user's cleaned folder.
- `Dockerfile` defaults to **2 Gunicorn workers** and **no longer uses
  `--preload`** (the master would open DB connections before forking, which is
  unsafe to share across worker processes with SQLite).
- README and `docs/architecture.md` / `docs/system-design.md` describe
  DB-backed state, the per-user directory layout, and the multi-worker
  deployment requirements. `docs/auth-api.md` documents
  `recovery_codes_available`.
- Test environment sets `CLEANUP_ENABLED=false` so the startup job never touches
  the working directory.

### Fixed
- **Empty recovery-code screen.** With `RECOVERY_CODE_COUNT=0`, enabling 2FA
  returned an empty list but the UI still displayed "Save your recovery codes".
  The screen is now skipped and the "use a recovery code" toggle hidden
  (including after a page reload, via a session flag).
- **Stale admin-link assertion.** The workspace test asserted a removed
  `id="admin-links"` element; corrected to the current `id="admin-link"` markup
  (a pre-existing failure introduced by an earlier merge).
- **Cleanup vs. tests.** Running the test suite started the real cleanup job
  against the working tree, deleting tracked files. Cleanup is now disabled in
  tests.

### Security
- Filenames are sanitized against path traversal on upload, output, and
  download paths.
- Deleting a file/analysis/NUBAN/intelligence item now removes its physical
  files from disk.
- The `pickle` state file is removed entirely, eliminating a deserialization
  risk; state is now stored as JSON in the database.
- Per-user isolation is enforced server-side on every endpoint.

### Performance
- Flat-memory streamed uploads (1 MB chunks).
- Non-blocking request path via background processing and status polling.
- CPU work offloaded via `run_cpu()`; a separate pool keeps auth/DB dependencies
  responsive during large-file processing.
- SQLite WAL allows concurrent readers alongside the single writer.

### Removed
- `app/core/state.py`: `file_db`, `analysis_db`, `nuban_db`, `intelsync_db`,
  `task_db`, `save_all_states()`, `load_all_states()`, `DB_FILE`, and the
  `pickle` import. `uploads/state_database.pkl` is no longer read or written.

### Dependencies
- Added `APScheduler==3.10.4` (with `pytz`, `six`, `tzlocal`) to
  `pyproject.toml` and `uv.lock`, and to `requirements.txt` for the legacy pip
  workflow.

### Deployment / migration notes
- State now lives in the database. For SQLite, `data/app.db` **must** reside on a
  persistent volume shared by all workers and across restarts. Set
  `DATABASE_URL` to PostgreSQL for multi-container/multi-host deployments.
- Default worker count is 2 (`WORKERS`, via the `Dockerfile`). Each worker opens
  its own database connections.
- The previous `uploads/state_database.pkl` is obsolete and can be deleted.

### Verification
- All 7 commits import the application successfully (`python -c "import main"`).
- `pytest` — 5/5 passing at `HEAD`.
- Confirmed cross-process state sharing: a value written by one OS process is
  readable by a second independent process, with `journal_mode=wal` active.

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
