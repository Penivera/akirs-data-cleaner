/*
 * Shared, cookie-free auth helpers for the AKIRS Data Toolkit.
 * Tokens live in localStorage; the MFA challenge lives in sessionStorage.
 * Every request authenticates with `Authorization: Bearer <access_token>`.
 */
(function (global) {
    'use strict';

    const ACCESS_KEY = 'akirs_access_token';
    const REFRESH_KEY = 'akirs_refresh_token';
    const CHALLENGE_KEY = 'akirs_mfa_challenge';
    const RETURN_KEY = 'akirs_return_to';

    const AUTH_PAGE = '/auth';
    const WORKSPACE_PAGE = '/app/process';

    let refreshing = null;

    // Filenames reach the browser verbatim, so they may contain spaces,
    // apostrophes and other characters that are unsafe inside a JS string or
    // a URL path. Percent-encode every segment (and nothing else) before the
    // request goes out.
    function encodeUrl(url) {
        const raw = String(url == null ? '' : url);
        const hashIndex = raw.indexOf('#');
        const hash = hashIndex === -1 ? '' : raw.slice(hashIndex);
        const withoutHash = hashIndex === -1 ? raw : raw.slice(0, hashIndex);
        const queryIndex = withoutHash.indexOf('?');
        const query = queryIndex === -1 ? '' : withoutHash.slice(queryIndex);
        const path = queryIndex === -1 ? withoutHash : withoutHash.slice(0, queryIndex);
        return path.split('/').map(encodeURIComponent).join('/') + query + hash;
    }

    function triggerOf(event, attribute) {
        const target = event.target;
        const el = target && target.closest ? target.closest('[' + attribute + ']') : null;
        return el;
    }

    const AKIRSAuth = {
        get access() { return localStorage.getItem(ACCESS_KEY); },
        get refresh() { return localStorage.getItem(REFRESH_KEY); },
        get challenge() { return sessionStorage.getItem(CHALLENGE_KEY); },

        setTokens(access, refresh) {
            if (access) localStorage.setItem(ACCESS_KEY, access);
            if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
        },
        setChallenge(token) { sessionStorage.setItem(CHALLENGE_KEY, token); },
        clearChallenge() { sessionStorage.removeItem(CHALLENGE_KEY); },
        clear() {
            localStorage.removeItem(ACCESS_KEY);
            localStorage.removeItem(REFRESH_KEY);
            sessionStorage.removeItem(CHALLENGE_KEY);
        },
        isAuthed() { return Boolean(this.access); },
        headers() { return this.access ? { Authorization: `Bearer ${this.access}` } : {}; },

        redirectToAuth() {
            if (location.pathname !== AUTH_PAGE) location.replace(AUTH_PAGE);
        },
        setReturnTo(path) {
            // Only same-origin paths may be restored, so a crafted link cannot
            // bounce a freshly authenticated user off to another origin.
            if (typeof path === 'string' && path.startsWith('/') && !path.startsWith('//')) {
                sessionStorage.setItem(RETURN_KEY, path);
            }
        },
        consumeReturnTo() {
            const path = sessionStorage.getItem(RETURN_KEY);
            sessionStorage.removeItem(RETURN_KEY);
            return path || null;
        },
        redirectToWorkspace() {
            // Honour a one-shot destination stashed before login (e.g. a
            // coworking invite link) so it survives the auth round-trip.
            location.replace(this.consumeReturnTo() || WORKSPACE_PAGE);
        },

        async refreshTokens() {
            if (!this.refresh) return false;
            if (!refreshing) {
                refreshing = fetch('/api/auth/refresh', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_token: this.refresh }),
                })
                    .then(async (res) => {
                        if (!res.ok) { this.clear(); return false; }
                        const data = await res.json();
                        this.setTokens(data.access_token, data.refresh_token);
                        return true;
                    })
                    .catch(() => { this.clear(); return false; })
                    .finally(() => { refreshing = null; });
            }
            return refreshing;
        },

        async apiFetch(url, options = {}) {
            const opts = {
                ...options,
                headers: { ...(options.headers || {}), ...this.headers() },
            };
            let res = await fetch(url, opts);
            if (res.status === 401 && await this.refreshTokens()) {
                opts.headers = { ...(options.headers || {}), ...this.headers() };
                res = await fetch(url, opts);
            }
            if (res.status === 401) { this.clear(); this.redirectToAuth(); }
            return res;
        },

        saveBlob(blob, filename) {
            const link = document.createElement('a');
            const objectUrl = URL.createObjectURL(blob);
            link.href = objectUrl;
            link.download = filename || 'download';
            document.body.appendChild(link);
            link.click();
            link.remove();
            // Revoking synchronously races the browser's own fetch of the blob
            // and truncates large files, so give it a moment to start.
            setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
        },

        async download(url, filename) {
            const notice = window.AKIRSNotify
                ? window.AKIRSNotify.progress(`Preparing ${filename || 'download'}…`)
                : null;
            try {
                const res = await this.apiFetch(encodeUrl(url));
                if (!res.ok) {
                    if (window.AKIRSNotify) window.AKIRSNotify.error('Download failed. The file may have expired.');
                    else window.alert('Download failed');
                    return;
                }
                this.saveBlob(await res.blob(), filename);
                if (window.AKIRSNotify) window.AKIRSNotify.success(`Downloaded ${filename || 'file'}`);
            } finally {
                if (notice) notice.remove();
            }
        },

        async view(url) {
            const notice = window.AKIRSNotify ? window.AKIRSNotify.progress('Opening report…') : null;
            try {
                const res = await this.apiFetch(encodeUrl(url));
                if (!res.ok) {
                    if (window.AKIRSNotify) window.AKIRSNotify.error('Unable to open the report.');
                    else window.alert('Unable to open report');
                    return;
                }
                const objectUrl = URL.createObjectURL(await res.blob());
                window.open(objectUrl, '_blank', 'noopener');
                setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
            } finally {
                if (notice) notice.remove();
            }
        },

        async submitDownloadForm(form) {
            const notice = window.AKIRSNotify ? window.AKIRSNotify.progress('Preparing your ZIP…') : null;
            try {
                const res = await this.apiFetch(form.action, {
                    method: (form.method || 'POST').toUpperCase(),
                    body: new FormData(form),
                });
                if (!res.ok) {
                    if (window.AKIRSNotify) window.AKIRSNotify.error('Download failed.');
                    else window.alert('Download failed');
                    return;
                }
                const disposition = res.headers.get('Content-Disposition') || '';
                const match = /filename="?([^";]+)"?/.exec(disposition);
                this.saveBlob(await res.blob(), match ? match[1] : 'AKIRS_download.zip');
                if (window.AKIRSNotify) window.AKIRSNotify.success('Download ready.');
            } finally {
                if (notice) notice.remove();
            }
        },

        async logout() {
            try {
                await this.apiFetch('/api/auth/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_token: this.refresh, all_devices: true }),
                });
            } catch (error) {
                /* ignore network errors and clear locally anyway */
            } finally {
                this.clear();
                location.replace(AUTH_PAGE);
            }
        },
    };

    // Attach the bearer token to every HTMX request.
    document.addEventListener('htmx:configRequest', (event) => {
        if (AKIRSAuth.access) event.detail.headers['Authorization'] = `Bearer ${AKIRSAuth.access}`;
    });

    // On 401, refresh once and retry; otherwise return to the login page.
    document.addEventListener('htmx:responseError', async (event) => {
        if (event.detail.xhr.status !== 401) return;
        if (await AKIRSAuth.refreshTokens()) {
            const cfg = event.detail.requestConfig;
            if (cfg && global.htmx) {
                global.htmx.ajax(cfg.verb, cfg.path, { target: cfg.target, headers: AKIRSAuth.headers() });
            }
            return;
        }
        AKIRSAuth.clear();
        AKIRSAuth.redirectToAuth();
    });

    // Intercept batch download forms rendered by HTMX.
    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (form && form.id === 'batch-download-form') {
            event.preventDefault();
            AKIRSAuth.submitDownloadForm(form);
        }
    });

    // Downloads and inline previews are driven by data attributes rather than
    // inline onclick handlers: a filename carrying an apostrophe, quote or
    // newline would otherwise terminate the JS string literal in the attribute
    // and the click would do nothing at all.
    document.addEventListener('click', (event) => {
        const downloadBtn = triggerOf(event, 'data-download-url');
        if (downloadBtn) {
            event.preventDefault();
            AKIRSAuth.download(downloadBtn.dataset.downloadUrl, downloadBtn.dataset.downloadName || '');
            return;
        }
        const viewBtn = triggerOf(event, 'data-view-url');
        if (viewBtn) {
            event.preventDefault();
            AKIRSAuth.view(viewBtn.dataset.viewUrl);
        }
    });

    global.AKIRSAuth = AKIRSAuth;
})(window);
