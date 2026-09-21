# Account pages

Open `/auth` for the combined login/create-account page. Use `/auth?mode=signup`
for the create-account tab. The existing green, gold, typography and crest are
reused; layout styles are scoped to `.auth-page` and do not change the workspace.

Additional page routes:

| Route | Page | Backend connection |
| --- | --- | --- |
| `/auth` | Login | `POST /api/auth/login` |
| `/auth?mode=signup` | Create account | Not available in this backend |
| `/auth/verify` | Email code or link verification | Not available |
| `/auth/setup` | Google Authenticator setup using a manual key | Not available |
| `/auth/pending` | Awaiting account approval by admin | Not available |
| `/auth/mfa` | Google Authenticator login code | Not available |

Per the requested scope, no registration, mail delivery, MFA, or approval APIs
were added. Unconnected forms show an unavailable message rather than pretending
to send email, create accounts, verify codes or approve access. They do not send
requests to invented endpoints. The setup key remains empty and copying is disabled.
The additional pages are not steps in the live login flow until their backend
contracts are supplied. Existing login authenticates directly into the workspace.

## Browser integration

Successful login retains the existing JSON token response and also sets an
HttpOnly, SameSite=Strict `akirs_access` cookie, valid for the access token lifetime.
The cookie is Secure on HTTPS or when `ADMIN_SESSION_HTTPS_ONLY=true`.
Bearer authentication remains supported and takes precedence over the cookie.
This makes normal navigation, HTMX, fetch requests and download links work with
the protected application routes without exposing tokens to browser JavaScript.

Unauthenticated HTML navigation to `/` redirects to `/auth`; protected APIs still
return 401. HTMX receives `HX-Redirect: /auth` when authentication expires.
Cross-origin writes are rejected. Auth responses and the workspace document
use `Cache-Control: no-store`. The browser requires another login after its access
token expires; the existing refresh API remains available to API clients.

The workspace logout control calls the existing logout endpoint with
`all_devices: true`, revoking tokens on all devices and clearing the browser cookie.
The admin dashboard retains its separate login and session.

## Checks

`python -m pytest tests/test_auth_pages.py -q` uses a temporary SQLite database and
test-only credentials. It checks public pages, protected navigation, cookie login,
HTMX access, Bearer compatibility, cross-origin rejection and logout revocation.
