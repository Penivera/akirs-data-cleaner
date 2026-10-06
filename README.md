# AKIRS Data Toolkit

AKIRS Data Toolkit is a browser-based application for cleaning batch customer
files, reviewing duplicates, analysing transactions, resolving Nigerian bank
accounts, and checking taxpayer intelligence against the AKIRS TMS database.
The interface uses FastAPI, Jinja templates, HTMX, and JavaScript.

## Features

- **Batch cleaning:** upload CSV or Excel workbooks, select worksheets, inspect a
  pre-flight file health report, detect headers, map fields automatically, and
  edit mappings. Retail, intelligence, and custom field presets are available.
- **Validation and branch filtering:** validate taxpayer IDs, BVNs, and NUBANs;
  select branches; inspect skipped rows; and export cleaned CSV files.
- **Duplicate review:** group duplicate records by a selected primary key or use
  similarity matching for intelligence records. Review groups and merge or pick
  records before export.
- **Optional live database checks:** compare uploaded records with AKIRS TMS,
  configure the query and target fields, optionally use fuzzy matching, then
  review matches and choose how to handle them.
- **Transaction analysis:** configure identity, metric, currency, and transaction
  flow fields; filter inflows/outflows and minimum amounts; keep selected source
  columns; concatenate name fields in a chosen order; and optionally aggregate
  cumulative transactions by NUBAN. Generate and download reports.
- **NUBAN account resolution:** map account and destination columns, select a
  bank, resolve account names through Paystack with Flutterwave fallback, and
  download the results.
- **Intelligence database sync:** map intelligence fields, check records against
  the live database, review matching options, and export unique records.
- **Account security:** self-service signup with administrator approval,
  mandatory TOTP two-factor authentication, JWT access
  and rotating refresh tokens, and individual or all-device logout.
- **Administrator tools:** manage and approve users, disable accounts, reset
  2FA, and review audit events through the superuser-only `/admin` dashboard.
- **Cookie-free application auth:** the workspace sends JWTs as Bearer headers,
  refreshes sessions, and uses authenticated downloads. The admin dashboard has
  its own session cookie.

## Run locally

Use Python 3. The project dependencies are listed in `requirements.txt`.

```bash
# Install requirements (assumes standard dependencies like fastapi, uvicorn, openpyxl)
pip install fastapi uvicorn openpyxl python-multipart

# Start the web interface
python bot.py
```
After starting the server, go to `http://localhost:8080/` via your web browser to upload Excel files and conduct the cleaning process.

### 2. Using the Standalone Scripts
If you want to manually run the migration with the hardcoded mappings (make sure the Excel files exist locally or adjust paths as needed in the script):
```bash
python migrate_data.py
```
This will generate and log the cleanup process straight to your terminal and save the output CSV in the same parent or `cleaned/` folder.

## Authentication & Admin

The application is protected by JWT authentication and ships with a
[Starlette Admin](https://jowilf.github.io/starlette-admin/) dashboard.

### How it works

- **Signup**: `POST /api/auth/signup` creates an account that must be approved by an
  administrator before it can sign in.
- **App API/UI**: stateless JWT sent in the `Authorization: Bearer <token>` header.
  Access tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30); refresh
  tokens after `REFRESH_TOKEN_EXPIRE_DAYS` (default 7). No cookies are used.
- **Two-factor authentication (mandatory)**: after approval, the first login forces
  TOTP setup with an authenticator app; later logins require a TOTP code (or a
  one-time recovery code). Tokens are only issued after the second factor passes.
- **Admin (`/admin`)**: Starlette Admin uses its own session cookie and is
  restricted to users with `is_superuser = True`. Admins approve/reject signups,
  reset 2FA, and review the audit log of actions by all users.
- **Storage**: SQLAlchemy. SQLite (`data/app.db`) by default; set `DATABASE_URL`
  to a PostgreSQL URL to switch.

### Auth endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/signup` | `{ "email", "password", "full_name" }` → pending approval |
| `POST` | `/api/auth/login` | `{ "email", "password" }` → MFA challenge |
| `POST` | `/api/auth/2fa/setup` | `{ "challenge_token" }` → TOTP secret + otpauth URI |
| `POST` | `/api/auth/2fa/enable` | `{ "challenge_token", "code" }` → tokens + recovery codes |
| `POST` | `/api/auth/2fa/verify` | `{ "challenge_token", "code"\|"recovery_code" }` → tokens |
| `POST` | `/api/auth/refresh` | `{ "refresh_token" }` → rotated token pair |
| `POST` | `/api/auth/logout` | `{ "refresh_token", "all_devices" }` → revoke tokens |
| `GET`  | `/api/auth/me` | Current user profile (Bearer required) |

### Managing users

A superuser is seeded on first startup from `ADMIN_EMAIL` / `ADMIN_PASSWORD`.
If `ADMIN_PASSWORD` is unset, a random password is generated and logged once.
Approve or reject signups, reset a user's 2FA, and review every upload, download,
processing, sync, and authentication event in the `/admin` audit log.

### Required environment variables

See `.env.example`. At minimum set a strong `SECRET_KEY`.

### User Data Isolation

Each user's files are stored in isolated directories (`uploads/{user_id}/`, `cleaned/{user_id}/`, `reports/{user_id}/`). Users can only see, process, and download their own files. All API endpoints enforce this isolation server-side.

### Automatic File Cleanup

A background job runs every `CLEANUP_INTERVAL_HOURS` (default: 24) and deletes files older than `CLEANUP_MAX_AGE_HOURS` (default: 24) from `uploads/`, `cleaned/`, and `reports/`, and purges the matching work-item and background-task rows from the database. This prevents disk space from filling up with stale uploads.

### State storage

Uploaded-file metadata, duplicate-review state, and background-task status are stored in the database (`work_items` and `tasks` tables) via `app/core/repository.py`, keyed by user. This is what lets multiple worker processes share state. On SQLite the engine runs in WAL mode with a busy timeout.

### File Upload Security

- Only `.xlsx`, `.xls`, and `.csv` files are accepted.
- Maximum upload size is `MAX_UPLOAD_SIZE_MB` (default: 50MB).
- Filenames are sanitized to prevent path traversal attacks.

### Performance

- **Streaming uploads**: Files are written to disk in 1MB chunks, so a 30MB file uses only ~1MB of RAM during upload (not 30MB).
- **Background processing**: File processing runs in FastAPI background tasks, so the HTTP request returns immediately and the user sees a "Processing..." status that auto-updates via polling.
- **Off-loop CPU work**: All heavy synchronous work (Excel/CSV parsing, record
  extraction, duplicate detection, CSV writing) runs on a dedicated bounded
  thread pool (`PROCESSING_THREADS`, default 2) via `app/core/executor.py`. This
  keeps the asyncio event loop responsive so one large file does not stall other
  users on a single-worker deployment.
- **Memory-efficient Excel reading**: `openpyxl` is used with `read_only=True` where possible to minimize memory footprint.

### Deployment note: worker processes

Application state (uploaded-file metadata, duplicate-review state, background
task status) is stored in the **database** via `app/core/repository.py`, so it
is shared across worker processes and survives restarts. The default deployment
runs **two Gunicorn workers** (`WORKERS=2`).

For SQLite this requires the `data/app.db` file to live on a **persistent,
single-host volume** (both workers and all restarts must see the same file).
The engine enables WAL mode and a busy timeout so concurrent workers do not
deadlock. If you deploy **multiple containers/replicas**, switch `DATABASE_URL`
to PostgreSQL — SQLite state does not work across hosts.

### Further reading

- [`docs/auth-api.md`](docs/auth-api.md) — full endpoint reference.
- [`docs/frontend-integration.md`](docs/frontend-integration.md) — wiring the UI
  to JWT (login, HTMX header injection, refresh, authenticated downloads).
- [`CHANGELOG.md`](CHANGELOG.md) — what changed and when.

