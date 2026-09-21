# Frontend Integration Guide — JWT Auth (No Cookies)

> Audience: frontend engineer. Backend auth is implemented; the UI is not.
> See `docs/auth-api.md` for the endpoint contract.

## The one thing to understand first

Auth is **stateless JWT in the `Authorization` header — no cookies.** Browsers do
**not** attach that header to:

- normal page navigations (clicking a link, typing a URL), or
- plain `<a href="...">` downloads.

They **do** attach it to `fetch`, `XMLHttpRequest`, and **HTMX** requests
(via `htmx:configRequest`).

So the UI must:

1. Be reachable through **public** pages that hold no data (login page + app shell).
2. Load all real content through **HTMX/fetch**, which injects the token.
3. Convert every authenticated **download link** into a JS `fetch` + blob save.
4. Handle `401` by refreshing the token and retrying, or sending the user to login.

---

## 1. Required backend support (small, coordinate with backend)

Today `/` is protected and returns `401` to a browser navigation. Add two
**public** routes so the cookie-free flow can start:

| Route | Auth | Renders |
|-------|------|---------|
| `GET /login` | public | `templates/login.html` |
| `GET /` | public | a **shell** (nav + empty `#main-content`, no data) |

Implementation sketch (register before the protected routers in `main.py`, and
remove the existing `read_index` from `routes.py` so there is no duplicate `/`):

```python
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

public_templates = Jinja2Templates(directory="templates")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return public_templates.TemplateResponse(request=request, name="login.html")

@app.get("/", response_class=HTMLResponse)
async def shell(request: Request):
    return public_templates.TemplateResponse(request=request, name="shell.html")
```

`shell.html` is `index.html` **without** the server-side
`{% include 'partials/process_view.html' %}`. The guard script (step 4) loads the
content over HTMX once a token exists. All data endpoints stay protected.

---

## 2. Token storage — `static/js/auth.js`

Store tokens in `localStorage` and expose small helpers. Add this file and load
it in both `login.html` and `shell.html` **before** `app.js` and after HTMX.

```js
const ACCESS_KEY = 'akirs_access_token';
const REFRESH_KEY = 'akirs_refresh_token';

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
  },
  isAuthed() { return Boolean(this.access); },
  headers() {
    return this.access ? { Authorization: `Bearer ${this.access}` } : {};
  },
};

// Single-flight refresh so parallel 401s don't all hit /refresh.
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

## 3. Login page — `templates/login.html`

Reuse the existing AKIRS styling (`/static/css/style.css`). Minimal markup:

```html
<form id="login-form">
  <input name="email" type="email" autocomplete="username" required>
  <input name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
  <p id="login-error" role="alert"></p>
</form>
<script src="/static/js/auth.js"></script>
<script>
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: form.get('email'), password: form.get('password') }),
    });
    if (res.ok) {
      const data = await res.json();
      auth.set(data.access_token, data.refresh_token);
      const next = new URLSearchParams(location.search).get('next') || '/';
      window.location.replace(next);
    } else {
      const err = await res.json().catch(() => ({}));
      document.getElementById('login-error').textContent = err.detail || 'Login failed';
    }
  });
</script>
```

If already logged in, `login.html` should immediately redirect to `/`:

```js
if (auth.isAuthed()) window.location.replace('/');
```

---

## 4. App shell guard + HTMX header injection

In `shell.html` (or `app.js`), before rendering content:

```js
if (!auth.isAuthed()) window.location.replace('/login');
```

Inject the header on **every** HTMX request and handle auth failures:

```js
document.body.addEventListener('htmx:configRequest', (e) => {
  if (auth.access) e.detail.headers['Authorization'] = `Bearer ${auth.access}`;
});

document.body.addEventListener('htmx:responseError', async (e) => {
  if (e.detail.xhr.status !== 401) return;

  if (await refreshTokens()) {
    // Re-issue the failed request with the new token.
    const cfg = e.detail.requestConfig;
    if (cfg) {
      htmx.ajax(cfg.verb, cfg.path, {
        target: cfg.target,
        headers: auth.headers(),
      });
    }
    return;
  }
  window.location.replace('/login');
});
```

> The existing nav in `index.html` already uses `hx-get` + `hx-target="#main-content"`,
> so once the header is injected the nav works unchanged.

---

## 5. Authenticated downloads (blob save)

`<a href="/api/download/...">` **cannot** carry the token. Replace every download
link (in `partials/cleaned_view.html`, `partials/data_view.html`,
`partials/analyse_file_card.html`, `partials/nuban_file_card.html`,
`partials/intelligence_file_card.html`) with a JS handler.

Add to `auth.js`:

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
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}
```

Usage:

```html
<!-- before -->
<a href="/api/download/{{ file.name }}">Download</a>

<!-- after -->
<button type="button"
        onclick="downloadFile('/api/download/{{ file.name }}', '{{ file.name }}')">
  Download
</button>
```

Batch download (`POST /api/download-batch`) takes form fields, so call it with
`apiFetch` and a `FormData` body, then save the returned blob the same way.

---

## 6. Logout + user menu

Add a logout control to the header in `shell.html`:

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

Optionally call `GET /api/auth/me` on shell load to show the user's email/name in
the header (also a good early check that the stored token is still valid).

---

## 7. Behaviour checklist

- [ ] Visiting `/` with no token redirects to `/login`.
- [ ] Wrong credentials show the error from `detail`; correct credentials land on `/`.
- [ ] After login, nav tabs load content via HTMX (token attached automatically).
- [ ] Let the access token expire (~30 min) and use the app: it refreshes silently
      and continues; if refresh fails, you land on `/login`.
- [ ] Every download works and does not navigate away.
- [ ] Logout clears storage and returns to `/login`; hitting Back does not show data.
- [ ] Refreshing the browser on `/` keeps you signed in (token in `localStorage`).
- [ ] `/admin` remains separate: it has its own login page and session cookie.

---

## 8. Security notes

- `localStorage` is readable by any script on the page, so it is vulnerable to
  XSS. Keep the app free of untrusted inline scripts; if you need stronger
  isolation, hold the access token in memory and the refresh token in
  `localStorage`, re-authenticating on reload.
- Always serve over **HTTPS** in production and set a strong backend
  `SECRET_KEY`. Set `ADMIN_SESSION_HTTPS_ONLY=true` for the admin cookie.
- Never put tokens in URLs or query strings.
- Refresh tokens rotate; always replace the stored refresh token with the one
  returned by `/api/auth/refresh`.
