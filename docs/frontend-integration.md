# Frontend Integration: Authentication and Protected Workspace

This guide describes the implemented browser flow in `static/js/auth-core.js`,
`static/js/auth.js`, and `static/js/session.js`. For request and response
schemas, see [auth-api.md](auth-api.md).

## Account flow

1. The public `/auth` page submits credentials to `POST /api/auth/login`.
   Signup submits to `POST /api/auth/signup`; newly created accounts must be
   approved by an administrator before login.
2. Login returns a short-lived `challenge_token`. The UI stores it in
   `sessionStorage` and routes to `/auth/setup` for first-time TOTP enrollment or
   `/auth/mfa` for an existing authenticator.
3. Setup calls `/api/auth/2fa/setup`, displays the QR code and manual key, then
   submits a code to `/api/auth/2fa/enable`. The response includes tokens and
   redirects to `/app`.
4. Existing users submit a TOTP code to
   `/api/auth/2fa/verify`. Successful verification returns tokens and opens
   `/app`.

## Token handling

`auth-core.js` stores access and refresh tokens in `localStorage` and the
temporary MFA challenge in `sessionStorage`. It provides `AKIRSAuth.apiFetch`
for authenticated requests, injects the Bearer header into HTMX requests, and
handles `401` responses by refreshing tokens and retrying. If refresh fails, it
clears credentials and redirects to `/auth`.

Use `AKIRSAuth` helpers for protected downloads and report viewing. A normal
browser navigation or plain `<a href>` does not attach the Bearer header; the
helpers fetch the resource with authorization and save/display the response.
Logout calls `POST /api/auth/logout` with the refresh token and can revoke the
current session or all devices.

## Protected workspace behavior

`/app` serves a data-free shell. `session.js` checks for a stored access token
and loads initial content from `/api/view/process` using authenticated HTMX
requests. The protected application routers require
`Authorization: Bearer <access_token>`. Browser navigation to protected `/`
redirects to `/auth`; HTMX receives `HX-Redirect: /auth` when authentication
expires. Auth and workspace responses are marked `Cache-Control: no-store`.

Application writes reject cross-origin requests. Static assets and account pages
remain public so the login experience can load before a user is authenticated.
The `/admin` UI is separate: Starlette Admin uses its own session cookie and
superuser authorization.

## Frontend entry points

- `templates/auth.html` with `static/js/auth.js` — signup, login, TOTP setup,
  MFA verification and pending approval screens.
- `templates/index.html` with `static/js/session.js` and `static/js/app.js` —
  guarded workspace and data-processing tabs.
- `static/js/auth-core.js` — token storage, authenticated fetch, HTMX header
  injection, refresh, and protected file operations.
