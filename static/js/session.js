(() => {
    'use strict';
    const auth = window.AKIRSAuth;

    // The workspace is Bearer-only, so guard the shell before rendering anything.
    if (!auth || !auth.isAuthed()) {
        // Preserve the deep link (a coworking invite or a specific tab) across
        // the login round-trip, so the user lands where they asked to go.
        if (/^\/(app|cowork\/join\/)/.test(location.pathname)) {
            auth?.setReturnTo(location.pathname + location.search);
        }
        location.replace('/auth');
        return;
    }

    const logout = document.getElementById('logout-button');
    logout?.addEventListener('click', () => {
        logout.disabled = true;
        auth.logout();
    });

    // Use the authenticated profile for the greeting and admin shortcut.
    async function loadAccountProfile() {
        try {
            const response = await auth.apiFetch('/api/auth/me');
            if (!response.ok) return;
            const me = await response.json();
            const username = typeof me.username === 'string' ? me.username.trim() : '';
            const firstName = typeof me.full_name === 'string' ? me.full_name.trim().split(/\s+/)[0] : '';
            const name = username || firstName;
            const welcome = document.getElementById('welcome-message');
            if (welcome) welcome.textContent = name ? `Welcome, ${name}` : 'Welcome';
            const adminLink = document.getElementById('admin-link');
            if (adminLink) adminLink.hidden = !me.is_superuser;
        } catch (error) {
            /* Keep a neutral greeting and hide the admin shortcut if the profile cannot load. */
        }
    }

    // --- Routing --------------------------------------------------------------
    // Each tab is a real path under /app, so the URL is the single source of
    // truth: refresh, back/forward, and a shared link all resolve to the same
    // view. htmx's own history cache is left unused on purpose — it snapshots
    // the whole document body, which is far too heavy for dataset panels and
    // overflows the localStorage quota on busy accounts.
    const DEFAULT_TAB = 'process';

    const shell = document.body.dataset;
    let currentSpace = shell.spaceId || '';
    const inviteToken = shell.inviteToken || '';

    /** The nav markup owns the tab list and each tab's endpoint. */
    const navItemFor = (tab) => document.querySelector(`.nav-item[data-tab="${tab}"]`);
    const isTab = (tab) => Boolean(navItemFor(tab));

    /** Turn a workspace URL into the {tab, space} pair it addresses. */
    function parseRoute(pathname) {
        const segments = pathname.split('/').filter(Boolean);
        if (segments[0] !== 'app' || !isTab(segments[1])) return null;
        let space = '';
        try {
            space = segments[1] === 'cowork' && segments[2] ? decodeURIComponent(segments[2]) : '';
        } catch (error) {
            /* A malformed id just falls back to the tab root. */
        }
        return { tab: segments[1], space };
    }

    const pathFor = (tab, space) =>
        space ? `/app/cowork/${encodeURIComponent(space)}` : `/app/${tab}`;

    function endpointFor(tab, space) {
        if (space) return `/api/cowork/spaces/${encodeURIComponent(space)}`;
        const item = navItemFor(tab);
        return item ? item.dataset.endpoint : '';
    }

    function markActiveTab(tab) {
        document.querySelectorAll('.nav-item').forEach((item) => {
            const isActive = item.dataset.tab === tab;
            item.classList.toggle('active', isActive);
            if (isActive) item.setAttribute('aria-current', 'page');
            else item.removeAttribute('aria-current');
        });
    }

    function render(tab, space) {
        const endpoint = endpointFor(tab, space);
        if (!endpoint) return;
        currentSpace = space || '';
        markActiveTab(tab);
        if (window.htmx) window.htmx.ajax('GET', endpoint, { target: '#main-content' });
    }

    /** Move to a view and record it in history so Back returns here. */
    function navigate(tab, space, { replace = false } = {}) {
        if (!isTab(tab)) return;
        const nextPath = pathFor(tab, space);
        if (location.pathname !== nextPath) {
            const state = { tab, space: space || '' };
            if (replace) history.replaceState(state, '', nextPath);
            else history.pushState(state, '', nextPath);
        }
        render(tab, space);
    }

    function initRouting() {
        if (window.__workspaceRoutingBound) return;
        window.__workspaceRoutingBound = true;

        // Tabs are plain links to real pages; htmx takes over the click to keep
        // the shell (and its bearer token) alive, while the href stays correct
        // for middle-click, "copy link", and no-JS fallback.
        document.querySelector('.top-nav')?.addEventListener('click', (event) => {
            const link = event.target.closest('.nav-item');
            if (!link || event.defaultPrevented || event.button !== 0) return;
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            // Coworking keeps its open space only while you stay on the tab.
            navigate(link.dataset.tab, link.dataset.tab === 'cowork' ? currentSpace : '');
        });

        // In-panel navigation (open a space, back to the list) declares where it
        // lands so the URL keeps matching what is actually on screen.
        document.addEventListener('click', (event) => {
            const trigger = event.target.closest('[data-nav-path]');
            if (!trigger || event.defaultPrevented || event.button !== 0) return;
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            const route = parseRoute(trigger.dataset.navPath);
            if (route) navigate(route.tab, route.space);
        });

        // A panel swapped in by a form post (creating a space, for instance)
        // carries its own canonical path; adopt it without a history entry.
        document.addEventListener('htmx:afterSwap', (event) => {
            if (event.detail?.target?.id !== 'main-content') return;
            const declared = event.detail.target.querySelector('[data-view-path]');
            const route = declared && parseRoute(declared.dataset.viewPath);
            if (!route) return;
            if (pathFor(route.tab, route.space) !== location.pathname) {
                history.replaceState({ tab: route.tab, space: route.space }, '', pathFor(route.tab, route.space));
            }
            markActiveTab(route.tab);
            currentSpace = route.space;
        });

        window.addEventListener('popstate', () => {
            const route = parseRoute(location.pathname);
            if (route) render(route.tab, route.space);
        });
    }

    window.AKIRSRouting = { navigate };

    async function loadInitialView() {
        loadAccountProfile();

        if (inviteToken) {
            try {
                const res = await auth.apiFetch('/api/cowork/join/' + encodeURIComponent(inviteToken), { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    // The invite token is spent; the joined space becomes the URL.
                    navigate('cowork', data.space_id, { replace: true });
                    return;
                }
            } catch (e) {}
        }

        const route = parseRoute(location.pathname) || { tab: DEFAULT_TAB, space: '' };
        // Links minted before tabs had their own paths still carry ?space=<id>.
        const legacySpace = route.tab === 'cowork' ? new URLSearchParams(location.search).get('space') : null;
        navigate(route.tab, route.space || legacySpace || '', { replace: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => { initRouting(); loadInitialView(); });
    } else {
        initRouting();
        loadInitialView();
    }
})();
