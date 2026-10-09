# Changelog

All notable changes to the AKIRS Data Toolkit are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Commit index

| Commit | Summary |
|---|---|
| `e61d992` | `chore(docs)` — capture durable product context in `PRODUCT.md` |
| `ed17e7b` | `refactor(ui)` — rebuild the design system and fix accessibility defects |
| `05637f9` | `feat(upload)` — accept uploads fast, analyse in the background, and make long work visible |
| `3466016` | `feat(analyse)` — mutually exclusive amount modes and a movement register |
| `3702a5d` | `feat(routing)` — make the URL the source of truth for workspace tabs |
| `b340f1e` | `fix(nuban)` — zero-pad 9-digit NUBANs instead of discarding them |

Detail for each commit follows, grouped by the kind of change it makes.

### Added

#### Nine-digit NUBANs are zero-padded instead of discarded
Batch ingestion validated NUBAN as "exactly 10 digits", so a 9-digit account
number was replaced with `N/A` and — because NUBAN is the retail preset's
primary key — the whole row was skipped and counted in the skipped-records
report. This is the usual shape of the data: bank exports often carry the
account number as a number, which drops the leading zero. A 9-digit NUBAN is now
left-padded to 10 digits, so the row is kept *and* the padded value becomes the
duplicate-grouping key, meaning `123456789` and `0123456789` are correctly
treated as one account rather than two. Applies to the retail and custom
presets wherever a `NUBAN` target is mapped. Other lengths (8 or fewer, 11+)
are still rejected, and valid 10-digit values are untouched.

The same repair is applied by the NUBAN resolver. It previously required a
10-character value and stamped anything shorter with the literal text
`Invalid NUBAN` in the output, so a 9-digit account number from a numeric
export was never looked up. It is now padded before the lookup, and the
corrected number is written back to the NUBAN column so the file shows the
number that was actually resolved. Only the 9-digit case is affected; every
other input behaves exactly as before.

#### Interface activity feedback
A large upload or a long resolve used to look identical to a frozen page, so
the first question a user had was whether the system had hung.

- A global request bar marks any in-flight request, so something is always
  visibly happening.
- Uploads report **real byte-level progress** and then switch to an explicit
  "Uploaded. Analysing the workbook…" phase, because the seconds users actually
  wait are the ones after the last byte lands.
- Upload failures are surfaced inline instead of vanishing — including an
  oversized file, which previously failed with no visible response at all.
- Buttons show a spinner while busy and a card's other actions are disabled, so
  a long job cannot be double-fired.
- Downloads and report opens announce progress and resolve to a success or a
  clear failure rather than appearing to do nothing until the save dialog.
- Loading states are accessible: `aria-live` status text, `role="progressbar"`
  with `aria-valuenow`, an assertive notification region, and
  `prefers-reduced-motion` support for every loading animation.

### Changed

#### One design system instead of per-screen styling
Styling had drifted into a dozen inline `style` attributes, hard-coded hexes,
and two systems layered on top of each other: the app had been dark, then
turned light, and the dark leftovers were never removed. `static/css/style.css`
is now a tokenized light system — semantic colours, spacing, radii, shadows,
focus rings — with the incumbent AKIRS identity preserved (institutional green,
official gold crest accent).

- **Emoji are no longer used as an icon system.** Every emoji (🔍 📥 ⚙️ 🚀 ❌
  📦 🗑️ …) is replaced by an authored SVG set in one stroke weight and
  currentColor, in `templates/partials/icons.html`.
- Empty, loading and error states now exist for every list and panel, including
  all four upload queues and the cleaned-datasets gallery.
- Browser surfaces are themed from the palette rather than left at defaults:
  text selection, scrollbars, focus rings, and tabular figures in numeric
  tables.
- Decorative kicker/eyebrow labels were removed from the auth screens and the
  thick accent top-border was dropped from cards; badges carry the preset
  meaning instead, and nested card-in-card framing was flattened.

#### Accessibility brought to WCAG 2.2 AA
The standard is now a product requirement, not an aspiration.

- The gold accent was used as text on white at **2.1:1**, which fails AA
  outright. Gold is now only ever a fill; accent wording uses a darker ink
  token that passes.
- Functional text below 11px was raised on the auth screens, and the low-contrast
  muted grey on the page background was brought back over the threshold.
- Every control has a visible focus ring; icon-only buttons, checkboxes, and
  member-removal controls now carry accessible names; the active nav item
  exposes `aria-current="page"`; a skip link precedes the shell.
- The DB-comparison view collapses from two columns to one on small screens
  rather than forcing a horizontal squeeze.

#### Analyse: heavy movements are recorded instead of netted away
A threshold review needs to see large movements. Netting hides them: an account
that takes in 431M and pays out 431M nets to zero and disappears from a
net-ranked report. Verified against the Q3 Polaris workbook, 24 accounts moving
100M or more were absent from the 35-row report for exactly this reason —
including one with 640M of credit turnover and one with 1.36B.

- Reports now carry a **movement register** alongside the ranked list. Every
  credit and debit is recorded as its own leg, before any netting, keyed by
  account (defaulting to the NUBAN column) rather than by name. Each leg carries
  its source spreadsheet row so a figure can be traced back.
- A **movement threshold** is applied to each leg separately, so a large debit
  cannot hide behind a small net. This is the filter a threshold review actually
  wants, as opposed to `min_amount_filter`, which compares the already-netted
  per-customer total.
- The register shows **credit, debit, gross and largest-single** for every
  account, and can be ordered by any of them, because they answer different
  questions: credit turnover is the assessable base for turnover tax, gross
  catches movement in either direction, and the largest single leg catches one
  extreme transaction.
- An **offsetting activity** section names accounts whose credit and debit are
  close enough to cancel — the shape a net-ranked report cannot show. It honours
  the same threshold as the table above it.

Fixed alongside:

- **A negative limit silently returned the wrong rows.** `-35` reached the report
  as `[:limit]`, i.e. `[:-35]`, which dropped the 35 smallest and kept 32 — and
  printed `TOP -35`. Negative limits are now refused and reported back in the
  form, and any non-positive value reaching the generator is treated as "no
  limit" rather than a reversed slice.
- **The register's account key defaults to the NUBAN column**, so customers who
  share a name are no longer pooled into one taxpayer by default.
- A threshold now applies to the offsetting section too, rather than being
  bypassed by it.

Totals and per-account arithmetic are unchanged: regenerating the Q3 report
reproduces 72 transactions, net NGN 7,224,838,816.19, inflows
NGN 26,135,545,141.84 and outflows NGN 18,910,706,325.65 exactly.

#### Analyse: "What are we measuring?" is now an explicit choice
Credit and debit columns were three optional dropdowns sitting beside a
mandatory metric column, which made a credit/debit file impossible to
configure: the form refused to save without a metric, and the hint text had to
explain an interaction that was never actually offered.

- The config form now asks which shape the file has — one amount column, or a
  credit/debit pair — and shows only that mode's fields. The inactive mode's
  selects are disabled so they cannot post a stale value, and the active mode's
  are required, so the form can no longer be blocked by a field the user cannot
  see.
- The save guard names the missing column ("Choose Credit column and Debit
  column before saving.") instead of silently doing nothing.
- `amount_mode` is stored with the config and is authoritative: whichever mode
  is chosen, the other one's columns are cleared on save. Before this a stale
  selection survived an edit and silently won at report time.
- Configs saved before the choice existed are inferred from their columns, so
  existing analyses keep producing the same report.

Fixed along the way:

- **An all-empty credit/debit row was booked as a 0.00 inflow.** It fell through
  to the sign-of-metric branch, was marked as an inflow, and therefore slipped
  past the "Inflows only" filter. Such a row now belongs to neither direction.
- **The minimum-amount filter dropped any account netting exactly zero**, because
  it tested the total for truthiness rather than comparing it.
- **NUBAN cumulative could not be combined with credit/debit columns.** It
  demanded a metric column and failed at generate time; it now honours the
  chosen amount mode.
- The credit/debit markers defaulted to `INFLOW`/`OUTFLOW` while the engine
  compared against `CR`/`DR`, so a freshly saved config matched nothing. They now
  default to empty, since CR and DR are always recognised.
- Editing a configured file back into an unsatisfiable state now returns it to
  "Ready" instead of leaving the card offering "Generate output".

#### Tabs are real URLs, so a refresh stays where you were
The six nav tabs were plain HTMX swaps: the URL never changed, so refreshing
always bounced back to Batch Process, the Back button never moved between tabs,
and a link could not be shared to a specific view.

- Each tab now has its own route under `/app` (`/app/process`, `/app/cleaned`,
  `/app/cowork`, `/app/analyse`, `/app/nuban`, `/app/intel`), and coworking
  spaces one level deeper (`/app/cowork/<space_id>`). Bare `/app` and unknown
  paths redirect to the default tab.
- The server renders the nav with the requested tab already active, so there is
  no flash of the wrong highlight before the panel loads.
- `static/js/session.js` owns routing: it reads the path, loads the matching
  panel, keeps the URL in step via `pushState`, and restores the right view on
  Back/Forward. htmx's own history cache is deliberately unused — it snapshots
  the whole document body, which is too heavy for dataset panels.
- Tabs are now real `<a href>` links, so middle-click, "copy link address", and
  a no-JS fallback all behave.
- Invite links (`/cowork/join/<token>`) and the join redirect now resolve to
  `/app/cowork/<space_id>`, and the pre-login destination keeps the full path
  (validated same-origin) across the auth round-trip.
- Coworking keeps the open space while you stay on that tab, and leaving the tab
  or hitting "Back to spaces" returns to `/app/cowork`.

#### Uploads accept fast and analyse in the background
Long uploads previously held the request open for the whole job (health audit,
header detection, field mapping, branch detection). The UI showed nothing while
that ran, and an oversized or malformed file failed silently.

- All four upload endpoints (`/api/upload`, `/api/analyse/upload`,
  `/api/nuban/upload`, `/api/intel/upload`) now only validate, stream to disk,
  and de-duplicate in the request, then hand analysis to a background task.
  Added `app/services/uploads.py` with the shared streaming/limit helper.
- Accepted files are created with status `Analysing...` and a tracked task
  (`ana_{id}`), so the card polls `/api/task-status` and reports its stage
  ("Running pre-flight health audit…", "Detecting headers…", "Mapping fields…")
  before refreshing itself with the final result.
- Filename-based preset detection stays in the request, so the card badge is
  correct the instant the card appears.
- New per-card refresh endpoints so every card type can poll itself:
  `/api/analyse/card/{id}`, `/api/nuban/card/{id}`, `/api/intel/card/{id}`
  (batch already had `/api/card/{id}`).
- Analysis completion is recorded in the audit log (`*_analysed`) alongside the
  existing accept-time entry.

### Fixed

- Deleting a file actually removes it from the screen. HTMX computes its
  `shouldSwap` as "status < 400 and status != 204", so the delete endpoints'
  `204 No Content` reply skipped the swap entirely and `hx-swap="delete"` never
  ran: the file and its data were gone server-side while the card stayed on
  screen until a manual refresh. The five delete endpoints now answer `200`.
- A file deleted while a background task was still running no longer comes back
  from the dead. `repository.put()` recreates a missing row, so a task that
  finished after the delete would resurrect the work item. Every background
  path (the four upload analysers, batch ingestion, and coworking bulk
  processing) now re-checks that the item still exists before writing.
- Coworking file delete uses an explicit `hx-swap="delete"` rather than relying
  on an empty `outerHTML` swap to blank the card.
- Destructive actions (file delete, coworking file delete, member removal) now
  confirm first and name what will be removed.

- Cards that are analysing or processing no longer get stuck on their loading
  state until a manual page refresh. HTMX fires `htmx:load` on each swapped-in
  element, so the file card is itself the event target; the enhancement scan
  only looked at descendants and therefore never bound the task poll for newly
  uploaded cards. Root-scoped scans now include the element they are handed.

- The Analyse and NUBAN configuration forms were partly **unreadable on a white
  background**. Dark-theme leftovers from an earlier revision survived in both
  forms: near-white `#f8fafc` labels, an `rgba(0,0,0,0.2)` sheet grid, and
  near-black text on light surfaces. Both forms were rewritten against the
  light system.
- File status indicators keyed their colour off the first word of the status
  label, so `"Needs Mapping"` produced `status-needs` and matched nothing — every
  "Needs…" state and every in-progress job rendered an invisible dot. Statuses
  are now normalised through a single mapping.
- Dragging a file over the upload zone left it with no border or background once
  the pointer left, because the drag handlers referenced `--glass-border` and
  `--glass-bg`, two custom properties that never existed.
- A dozen class names used by the templates had no rule at all
  (`btn-success`, `btn-warning`, `form-actions`, `file-actions`, `main-content`,
  `preview-section`, `--accent-light`), which left controls unstyled and panels
  without their spacing.
- The mapping form resolved `#duplicate-logic-field` through
  `document.getElementById`, which returns the *first* match and so read the
  wrong element once more than one card was open. Handlers are now scoped to
  their own form.

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
