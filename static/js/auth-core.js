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

    const AUTH_PAGE = '/auth';
    const WORKSPACE_PAGE = '/app';

    let refreshing = null;

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
        redirectToWorkspace() {
            location.replace(WORKSPACE_PAGE);
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
            link.href = URL.createObjectURL(blob);
            link.download = filename || 'download';
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(link.href);
        },

        async download(url, filename) {
            const res = await this.apiFetch(url);
            if (!res.ok) { window.alert('Download failed'); return; }
            this.saveBlob(await res.blob(), filename);
        },

        async view(url) {
            const res = await this.apiFetch(url);
            if (!res.ok) { window.alert('Unable to open report'); return; }
            const objectUrl = URL.createObjectURL(await res.blob());
            window.open(objectUrl, '_blank', 'noopener');
            setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
        },

        async submitDownloadForm(form) {
            const res = await this.apiFetch(form.action, {
                method: (form.method || 'POST').toUpperCase(),
                body: new FormData(form),
            });
            if (!res.ok) { window.alert('Download failed'); return; }
            const disposition = res.headers.get('Content-Disposition') || '';
            const match = /filename="?([^";]+)"?/.exec(disposition);
            this.saveBlob(await res.blob(), match ? match[1] : 'AKIRS_download.zip');
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

    global.AKIRSAuth = AKIRSAuth;
})(window);
