# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

AKIRS (Akwa Ibom State Internal Revenue Service) internal tax officers and audit
staff. They work with messy raw data as part of daily tax administration:
bank extracts, retail tax filings, and taxpayer intelligence records that arrive
as CSV or Excel workbooks and must be cleaned, checked, and standardized before
they are usable. Secondary audience: superuser administrators who approve
signups, disable accounts, reset 2FA, and review the audit log through `/admin`.

## Product Purpose

An internal administrative platform that turns messy batch customer files into
clean, standardized, auditable datasets. It uploads and health-checks workbooks,
detects headers, maps fields to tax-domain targets, validates taxpayer identity,
resolves Nigerian bank accounts, reviews duplicates, analyses transactions, and
verifies records against the live AKIRS TMS database — then exports cleaned
datasets and reports. Success means staff stop doing this by hand in
spreadsheets, and every output is traceable to a verifiable, audited process.

## Positioning

Two capabilities a neighboring tool could not truthfully copy:

1. **Live AKIRS TMS intelligence-database access.** Uploaded records can be
   checked against the live AKIRS Tax Management System via a privileged
   `INTELLIGENCE_TOKEN`, then matched, flagged, and exported. This access is not
   replicable outside AKIRS.
2. **Nigerian bank resolution fused with tax-domain validation.** Paystack NUBAN
   resolution (with Flutterwave fallback) combined with TIN/BVN/NUBAN validation
   and retail/intelligence field presets in one end-to-end workflow.

## Operating Context

- Inputs: CSV and Excel (`.xlsx`, `.xls`) bank extracts, retail tax filings, and
  taxpayer intelligence records; uploaded per user and deduplicated by SHA-256.
- Batch cleaner pipeline: structural health report (0–100) → header detection →
  branch detection → auto field mapping (retail / intelligence / custom presets)
  → extract and validate records → deduplicate (exact primary key or fuzzy
  sorted-neighborhood) → optional live DB verification → export cleaned CSV.
- Duplicate review groups records and lets the user merge or pick before export.
- Transaction analysis configures identity/metric/currency/flow fields, filters
  inflows/outflows, concatenates name fields, optionally aggregates cumulative
  transactions by NUBAN, and generates downloadable reports.
- NUBAN resolver maps account and destination columns, selects a bank, and
  resolves account names through Paystack/Flutterwave.
- Intelligence sync checks records against the live database and exports unique
  records.
- Admin dashboard (`/admin`) uses its own session cookie; it is superuser-only.
- Files are stored per user under `uploads/{user_id}/`, `cleaned/{user_id}/`,
  `reports/{user_id}/`; a background job purges files older than the configured
  age.
- Deployed for AKIRS in a controlled on-prem / private-cloud environment.

## Capabilities and Constraints

- Stack (existing codebase, not a choice to revisit): FastAPI, Jinja2 templates,
  vendored HTMX, vanilla JavaScript, SQLAlchemy, Starlette Admin, openpyxl,
  httpx, Pydantic Settings.
- Persistence: SQLite (`data/app.db`) for development only; production requires
  a PostgreSQL `DATABASE_URL`. Workflow state (work items, background tasks)
  lives in the database and is shared across Gunicorn worker processes.
- Heavy CPU work (parsing, extraction, dedupe, CSV writing) runs on a bounded
  thread pool so the async event loop stays responsive; uploads stream in 1MB
  chunks.
- Upload constraints: only `.xlsx`, `.xls`, `.csv`; max size `MAX_UPLOAD_SIZE_MB`
  (default 50MB); filenames sanitized against path traversal.
- Required secrets/config: `SECRET_KEY`, `DATABASE_URL`, Paystack and Flutterwave
  keys, and the AKIRS TMS `INTELLIGENCE_TOKEN`. Real credentials are not in the
  repo.
- Application auth is cookie-free (JWT Bearer in the browser); only the admin
  dashboard uses a session cookie.
- Documentation drift to reconcile in future work: `README.md` describes
  database-backed state, while `docs/architecture.md` §2 still describes an
  in-memory/pickle state model. Treat the repository code as the source of truth.

## Brand Commitments

- The AKIRS name and official government identity are binding: this is presented
  as the official administrative platform of the Akwa Ibom State Internal
  Revenue Service.
- The Akwa Ibom State coat of arms / crest (`static/akirs.png`) is the existing
  official emblem and must be preserved as the product's identity mark.
- Tone is institutional, precise, and administrative, matching the official
  AKIRS presence (`akirs.ak.gov.ng`).

## Evidence on Hand

- Official emblem asset at `static/akirs.png`.
- Architecture and flow diagrams under `docs/` (`01_system_context.png` through
  `07_state_model.png`), plus `docs/architecture.md`, `docs/auth-api.md`,
  `docs/frontend-integration.md`, and `docs/data-flow.md`.
- `CHANGELOG.md` records product history.

Absent and not to be fabricated: testimonials, named customers, benchmarks,
pricing, licensing terms, or deployment claims beyond the configuration and
README. External integrations require live API keys that are not in the repo.

## Product Principles

1. **Operate-first.** This is a working tool for a task; scanability,
   consistency, and efficiency outrank visual expression.
2. **Trust through verifiability.** Every cleaned output and resolution should be
   traceable and covered by the audit trail.
3. **Tax-domain by default.** Presets, validation rules, and terminology are
   tuned to Nigerian tax administration, not generic data cleaning.
4. **Isolation is non-negotiable.** Per-user data isolation and mandatory 2FA are
   product facts, never optional conveniences.
5. **Never invent data.** Where real records, keys, or evidence are missing,
   surface the gap rather than fabricating.

## Accessibility & Inclusion

The interface must meet **WCAG 2.2 AA**: sufficient contrast, full keyboard
operability, visible focus, adequate target sizes, and correct semantics for the
data-heavy forms, tables, and review workflows.
