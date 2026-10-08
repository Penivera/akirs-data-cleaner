(() => {
    'use strict';
    const auth = window.AKIRSAuth;

    // The workspace is Bearer-only, so guard the shell before rendering anything.
    if (!auth || !auth.isAuthed()) {
        // Preserve a coworking invite link across the login round-trip.
        if (location.pathname.startsWith('/cowork/join/')) {
            auth?.setReturnTo(location.pathname);
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

    async function loadInitialView() {
        loadAccountProfile();

        if (location.pathname.startsWith('/cowork/join/')) {
            const token = location.pathname.split('/cowork/join/')[1].split('/')[0];
            try {
                const res = await auth.apiFetch('/api/cowork/join/' + token, { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    window.history.replaceState({}, '', '/app');
                    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
                    document.getElementById('nav-cowork')?.classList.add('active');
                    if (window.htmx) {
                        window.htmx.ajax('GET', '/api/cowork/spaces/' + data.space_id, { target: '#main-content' });
                        return;
                    }
                }
            } catch (e) {}
        }

        const urlParams = new URLSearchParams(window.location.search);
        const spaceId = urlParams.get('space');
        if (spaceId) {
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.getElementById('nav-cowork')?.classList.add('active');
            if (window.htmx) {
                window.htmx.ajax('GET', '/api/cowork/spaces/' + encodeURIComponent(spaceId), { target: '#main-content' });
                return;
            }
        }

        if (window.htmx) window.htmx.ajax('GET', '/api/view/process', { target: '#main-content' });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadInitialView);
    } else {
        loadInitialView();
    }
})();
