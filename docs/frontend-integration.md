# Frontend Integration Guide — JWT Auth, Signup & TOTP 2FA (No Cookies)

> **Status: implemented (2026-09-21).** The flow below is live in
> `static/js/auth-core.js`, `static/js/auth.js`, `static/js/session.js`,
> `templates/auth.html`, and the public `/app` shell. This document is kept as the
> reference for how the pieces fit together and for future changes.

> Audience: frontend engineer. See `docs/auth-api.md` for the endpoint contract.

## The one thing to understand first

Auth is **stateless JWT in the `Authorization` header — no cookies.** Browsers do
**not** attach that header to normal page navigations or plain `<a href>` downloads,
but they **do** attach it to `fetch`/`XHR` and **HTMX** requests (via
`htmx:configRequest`).

So the UI must:

1. Have **public** pages that hold no data: login, signup, 2FA screens, and the app shell.
2. Load all real content through **HTMX/fetch**, which inject the token.
3. Convert authenticated **download links** into JS `fetch` + blob saves.
4. Handle `401` by refreshing and retrying, or sending the user to login.

Account lifecycle the UI must support: **signup → pending approval → login →
mandatory 2FA setup (first time) → 2FA verify (later) → app**.

---

## 1. Required backend support (small, coordinate with backend)

`/` is protected and returns `401` to browser navigation. Add these **public**
routes so the cookie-free flow can start (register before the protected routers in
`main.py`, and remove the existing `read_index` from `routes.py`):

| Route | Renders |
|-------|---------|
| `GET /login` | `templates/login.html` |
| `GET /signup` | `templates/signup.html` |
| `GET /mfa` | `templates/mfa.html` (setup + verify, or split into two pages) |
| `GET /` | a **shell** (nav + empty `#main-content`, no data) |

```python
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

public_templates = Jinja2Templates(directory="templates")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return public_templates.TemplateResponse(request=request, name="login.html")

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return public_templates.TemplateResponse(request=request, name="signup.html")

@app.get("/mfa", response_class=HTMLResponse)
async def mfa_page(request: Request):
    return public_templates.TemplateResponse(request=request, name="mfa.html")

@app.get("/", response_class=HTMLResponse)
async def shell(request: Request):
    return public_templates.TemplateResponse(request=request, name="shell.html")
```

All data endpoints stay protected.

---

## 2. Token + challenge storage — `static/js/auth.js`

Tokens in `localStorage`; the transient **challenge token** in `sessionStorage`
(it is only needed for the 2FA step). Load this file on every public page before
`app.js`.

```js
const ACCESS_KEY = 'akirs_access_token';
const REFRESH_KEY = 'akirs_refresh_token';
const CHALLENGE_KEY = 'akirs_mfa_challenge';

const auth = {
  get access() { return localStorage.getItem(ACCESS_KEY); },
  get refresh() { return localStorage.getItem(REFRESH_KEY); },
  set(access, refresh) {
    localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    sessionStorage.removeItem(CHALLENGE_KEY);
  },
  isAuthed() { return Boolean(this.access); },
  headers() {
    return this.access ? { Authorization: `Bearer ${this.access}` } : {};
  },
  setChallenge(token) { sessionStorage.setItem(CHALLENGE_KEY, token); },
  get challenge() { return sessionStorage.getItem(CHALLENGE_KEY); },
  clearChallenge() { sessionStorage.removeItem(CHALLENGE_KEY); },
};

let refreshing = null;
async function refreshTokens() {
  if (!auth.refresh) return false;
  if (!refreshing) {
    refreshing = fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: auth.refresh }),
    })
      .then(async (res) => {
        if (!res.ok) { auth.clear(); return false; }
        const data = await res.json();
        auth.set(data.access_token, data.refresh_token);
        return true;
      })
      .catch(() => { auth.clear(); return false; })
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}
```

---

## 3. Signup page — `templates/signup.html`

```html
<form id="signup-form">
  <input name="full_name" type="text" required>
  <input name="email" type="email" autocomplete="username" required>
  <input name="password" type="password" autocomplete="new-password" minlength="8" required>
  <button type="submit">Create account</button>
  <p id="signup-msg" role="alert"></p>
</form>
<script src="/static/js/auth.js"></script>
<script>
  document.getElementById('signup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const res = await fetch('/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: f.get('email'),
        password: f.get('password'),
        full_name: f.get('full_name'),
      }),
    });
    const body = await res.json().catch(() => ({}));
    const msg = document.getElementById('signup-msg');
    if (res.status === 201) {
      msg.textContent = 'Account created. An administrator must approve it before you can sign in.';
      msg.className = 'success';
      e.target.reset();
    } else {
      msg.textContent = body.detail || 'Signup failed';
      msg.className = 'error';
    }
  });
</script>
```

On success, show the "pending approval" message. Do **not** attempt to log in.

---

## 4. Login page — `templates/login.html`

Login no longer returns tokens. It returns an MFA challenge; route the user to the
2FA screen.

```js
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: f.get('email'), password: f.get('password') }),
  });
  const body = await res.json().catch(() => ({}));
  const err = document.getElementById('login-error');

  if (res.status === 200) {
    auth.setChallenge(body.challenge_token);
    // setup_required -> first-time 2FA setup; mfa_required -> verify
    window.location.replace('/mfa');
    return;
  }
  if (res.status === 403 && /pending/i.test(body.detail || '')) {
    err.textContent = 'Your account is awaiting administrator approval.';
  } else {
    err.textContent = body.detail || 'Login failed';
  }
});
```

If already authed, redirect to `/`; add a link to `/signup`.

---

## 5. 2FA page — `templates/mfa.html`

Handles both **setup** (first login) and **verify** (later logins), decided by
calling `/2fa/setup`:

```js
if (!auth.challenge) window.location.replace('/login');

const res = await fetch('/api/auth/2fa/setup', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ challenge_token: auth.challenge }),
});

if (res.status === 200) {
  // First login: show QR + code input, then call /2fa/enable
  const { secret, otpauth_url } = await res.json();
  renderQr(otpauth_url);            // see note below
  showSetupForm(secret);
} else {
  // Already configured: show code / recovery-code input, then call /2fa/verify
  showVerifyForm();
}
```

- The setup response includes `qr_svg`, an SVG data URI generated server-side.
  Put it straight into `<img src>` so the user can **scan the QR code**; show
  `secret` as a manual-entry fallback. No client-side QR library is needed.
- **Enable** (first login): POST `/api/auth/2fa/enable` with
  `{ challenge_token, code }`. On `200`, store tokens, then **show the returned
  `recovery_codes` once** and require the user to acknowledge before continuing.
- **Verify** (later): POST `/api/auth/2fa/verify` with
  `{ challenge_token, code }` or `{ challenge_token, recovery_code }`. On `200`,
  store tokens and go to `/`.

```js
function onMfaSuccess(data, recoveryCodes) {
  auth.set(data.access_token, data.refresh_token);
  auth.clearChallenge();
  if (recoveryCodes && recoveryCodes.length) {
    showRecoveryCodesOnce(recoveryCodes); // user must copy/save, then continue
  } else {
    window.location.replace('/');
  }
}
```

Handle `400` (wrong code) and `401` (expired challenge → back to `/login`).

---

## 6. App shell guard + HTMX header injection

In `shell.html` (or `app.js`), before rendering content:

```js
if (!auth.isAuthed()) window.location.replace('/login');
```

Inject the header on every HTMX request and handle auth failures:

```js
document.body.addEventListener('htmx:configRequest', (e) => {
  if (auth.access) e.detail.headers['Authorization'] = `Bearer ${auth.access}`;
});

document.body.addEventListener('htmx:responseError', async (e) => {
  if (e.detail.xhr.status !== 401) return;
  if (await refreshTokens()) {
    const cfg = e.detail.requestConfig;
    if (cfg) htmx.ajax(cfg.verb, cfg.path, { target: cfg.target, headers: auth.headers() });
    return;
  }
  window.location.replace('/login');
});
```

The existing nav (`hx-get` + `hx-target="#main-content"`) works unchanged once the
header is injected.

---

## 7. Authenticated downloads (blob save)

Replace every `<a href="/api/download/...">` with a JS handler.

```js
async function apiFetch(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}), ...auth.headers() } };
  let res = await fetch(url, opts);
  if (res.status === 401 && await refreshTokens()) {
    opts.headers = { ...(options.headers || {}), ...auth.headers() };
    res = await fetch(url, opts);
  }
  if (res.status === 401) { auth.clear(); window.location.replace('/login'); }
  return res;
}

async function downloadFile(url, filename) {
  const res = await apiFetch(url);
  if (!res.ok) { alert('Download failed'); return; }
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename || 'download';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
}
```

```html
<button type="button"
        onclick="downloadFile('/api/download/{{ file.name }}', '{{ file.name }}')">Download</button>
```

---

## 8. Logout + user menu

```js
async function logout() {
  try {
    await apiFetch('/api/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: auth.refresh, all_devices: false }),
    });
  } finally {
    auth.clear();
    window.location.replace('/login');
  }
}
```

Call `GET /api/auth/me` on shell load to show the user's name/email and confirm the
token is still valid.

---

## 9. Behaviour checklist

- [ ] `/signup` creates an account and shows the "pending approval" message.
- [ ] Logging in before approval shows the pending message (403).
- [ ] After approval, first login routes to 2FA setup; QR renders; wrong code shows an error.
- [ ] Enabling 2FA shows the recovery codes once and stores tokens on acknowledgement.
- [ ] Later logins ask for a code; a recovery code also works, and cannot be reused.
- [ ] `/` with no token redirects to `/login`.
- [ ] Nav tabs load content via HTMX (token attached automatically).
- [ ] After ~30 min the app refreshes silently; on refresh failure you land on `/login`.
- [ ] Every download works and does not navigate away.
- [ ] Logout clears storage and returns to `/login`; Back does not reveal data.
- [ ] Refreshing `/` keeps you signed in (token in `localStorage`).
- [ ] `/admin` stays separate (own login + session cookie) for approvers.

---

## 10. Security notes

- `localStorage` is readable by any script on the page (XSS risk). Keep the app free
  of untrusted inline scripts; for stronger isolation, hold the access token in
  memory and the refresh token in `localStorage`, re-authenticating on reload.
- Always serve over **HTTPS** in production; set a strong backend `SECRET_KEY` and
  `ADMIN_SESSION_HTTPS_ONLY=true`.
- Never put tokens in URLs or query strings.
- Refresh tokens rotate; always replace the stored refresh token with the one from
  `/api/auth/refresh`.
- The MFA `challenge_token` is short-lived; clear it after use and on failure.
