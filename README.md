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
python -m venv .venv
# Activate the environment, then:
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/auth` to sign in or create an account. New accounts
remain pending until an administrator approves them. Set the environment
variables described in [deploy.md](deploy.md) before deploying. In particular,
configure a strong `SECRET_KEY`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD`. The app
creates the first administrator at startup; if `ADMIN_PASSWORD` is omitted, a
random password is written to the application log.

## Application pages

- `/auth` — login and signup; related public routes include `/auth/setup`,
  `/auth/mfa`, and `/auth/pending`.
- `/app` — authenticated workspace shell.
- `/admin` — administrator dashboard for approved superusers.
- `/docs` — FastAPI OpenAPI documentation.

## Configuration and storage

Authentication data uses SQLAlchemy, with SQLite at `data/app.db` by default;
set `DATABASE_URL` to use PostgreSQL. Uploaded files and generated artifacts are
stored on the server. Workflow state is held in memory and persisted to
`uploads/state_database.pkl`; use a persistent, access-controlled data directory
in deployment. External features require their relevant credentials, such as
Paystack/Flutterwave keys for NUBAN resolution and the intelligence token and URL
for AKIRS TMS checks. See [deploy.md](deploy.md) and `app/core/config.py` for
configuration names.

## Documentation

- [Authentication API](docs/auth-api.md) — signup, approval, MFA, tokens, and
  endpoint contracts.
- [Account pages](docs/auth-pages.md) — browser account and workspace flows.
- [Frontend integration](docs/frontend-integration.md) — token handling,
  authenticated HTMX requests, refresh, and downloads.
- [Architecture](docs/architecture.md) and [system design](docs/system-design.md)
  — application modules and data flow.
- [Sample payloads](docs/sample-payloads.md) — example API payloads.
- [Changelog](CHANGELOG.md) — feature and behavior history.
