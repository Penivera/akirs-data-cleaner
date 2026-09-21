# Account pages

> **Updated 2026-09-21 — frontend implemented.** The account pages now implement
> the Bearer-only, mandatory-2FA flow. Tokens are stored in `localStorage`; the
> MFA challenge in `sessionStorage`; no auth cookie is used. The workspace shell
> is served publicly at `/app` and loads content over HTMX with the bearer token.
> See [`frontend-integration.md`](frontend-integration.md) for the underlying
> patterns.

## Public pages

`/auth` and its sub-routes are public and hold no data:

| Route | Page | Backend |
| --- | --- | --- |
| `/auth` | Login / create account | `POST /api/auth/login`, `POST /api/auth/signup` |
| `/auth/setup` | TOTP setup (setup key + code) | `POST /api/auth/2fa/setup`, `/2fa/enable` |
| `/auth/mfa` | TOTP / recovery-code login | `POST /api/auth/2fa/verify` |
| `/auth/recovery` | One-time recovery codes | returned by `/2fa/enable` |
| `/auth/pending` | Awaiting admin approval | informational |
| `/app` | Workspace shell (no data) | loads `/api/view/process` via HTMX |

The green/gold styling is scoped to `.auth-page` and does not affect the workspace.

## Current backend behaviour

- **Signup, approval and mandatory 2FA are implemented** (see `docs/auth-api.md`).
  New accounts are pending until an admin approves them, and every user must set up
  TOTP on first login.
- **Login returns `MfaChallengeResponse`** (`mfa_required` / `setup_required` /
  `challenge_token`). Tokens are only issued after the second factor.
- **No auth cookie is set.** `get_current_user` reads `Authorization: Bearer`
  only. The earlier `akirs_access` cookie fallback was removed.
- Unauthenticated HTML navigation to `/` redirects to `/auth`; protected APIs
  return `401`. HTMX receives `HX-Redirect: /auth` when authentication expires.
- Cross-origin writes are rejected. Auth responses and the workspace document use
  `Cache-Control: no-store`.

## Implemented browser flow

1. `/auth` login → `POST /api/auth/login`; route on the challenge
   (`setup_required` → `/auth/setup`, `mfa_required` → `/auth/mfa`), storing
   `challenge_token` in `sessionStorage`.
2. `/auth/setup` → `POST /api/auth/2fa/setup` (shows the setup key), then
   `POST /api/auth/2fa/enable`; stores tokens and shows recovery codes once.
3. `/auth/mfa` → `POST /api/auth/2fa/verify` with a TOTP or recovery code; stores
   tokens and redirects to `/app`.
4. Signup → `POST /api/auth/signup`, then the pending-approval state.
5. `static/js/auth-core.js` attaches `Authorization: Bearer` to HTMX/fetch and
   powers authenticated downloads; `static/js/session.js` guards `/app` and wires
   logout.

## Checks

`python -m pytest tests/test_auth_pages.py -q` uses a temporary SQLite database and
test-only credentials. It checks public pages, the `/app` shell, protected
navigation, the MFA challenge login flow, Bearer access, HTMX redirect and
cross-origin rejection.
