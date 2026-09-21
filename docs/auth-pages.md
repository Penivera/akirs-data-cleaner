# Account pages

> **Updated 2026-09-21 — backend contract changed.** The browser flow was built
> against the pre-2FA contract (login returned tokens and an HttpOnly
> `akirs_access` cookie). Authentication is now **Bearer-only (no auth cookie)**
> and **login returns an MFA challenge**, not tokens. The account pages and their
> JavaScript must be updated to the flow in
> [`frontend-integration.md`](frontend-integration.md). The notes below describe
> the current backend reality.

## Public pages

`/auth` and its sub-routes are public and hold no data:

| Route | Intended page | Backend |
| --- | --- | --- |
| `/auth` | Login | `POST /api/auth/login` → MFA challenge |
| `/auth?mode=signup` | Create account | `POST /api/auth/signup` (implemented) |
| `/auth/pending` | Awaiting admin approval | informational |
| `/auth/setup` | TOTP setup (QR + code) | `POST /api/auth/2fa/setup` then `/2fa/enable` |
| `/auth/mfa` | TOTP / recovery-code login | `POST /api/auth/2fa/verify` |

The green/gold styling is scoped to `.auth-page` and does not affect the workspace.

## Current backend behaviour

- **Signup, approval and mandatory 2FA are implemented** (see
  `docs/auth-api.md`). New accounts are pending until an admin approves them, and
  every user must set up TOTP on first login.
- **Login returns `MfaChallengeResponse`** (`mfa_required` / `setup_required` /
  `challenge_token`). Tokens are only issued after the second factor.
- **No auth cookie is set.** `get_current_user` reads `Authorization: Bearer`
  only. The earlier `akirs_access` cookie fallback was removed.
- Unauthenticated HTML navigation to `/` redirects to `/auth`; protected APIs
  return `401`. HTMX receives `HX-Redirect: /auth` when authentication expires.
- Cross-origin writes are rejected. Auth responses and the workspace document use
  `Cache-Control: no-store`.

## Frontend work still required

The account pages currently treat signup/MFA as "not available" and the login
form assumes a cookie is set on success. To match the backend:

1. Wire `/auth` login to route on the challenge (`setup_required` → `/auth/setup`,
   `mfa_required` → `/auth/mfa`), storing `challenge_token` in `sessionStorage`.
2. Implement `/auth/setup` (render `otpauth_url` as a QR, POST `/2fa/enable`,
   show recovery codes once) and `/auth/mfa` (POST `/2fa/verify`).
3. Wire signup to `POST /api/auth/signup` and show the pending-approval state.
4. Store the returned tokens and attach `Authorization: Bearer` to HTMX/fetch and
   authenticated downloads (no cookies).

See [`frontend-integration.md`](frontend-integration.md) for code snippets.

## Checks

`python -m pytest tests/test_auth_pages.py -q` uses a temporary SQLite database and
test-only credentials. It checks public pages, protected navigation, the MFA
challenge login flow, Bearer access, HTMX redirect and cross-origin rejection.
