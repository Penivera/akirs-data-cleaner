(() => {
    'use strict';
    const auth = window.AKIRSAuth;

    // The workspace is Bearer-only, so guard the shell before rendering anything.
    if (!auth || !auth.isAuthed()) {
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

    function loadInitialView() {
        loadAccountProfile();
        if (window.htmx) window.htmx.ajax('GET', '/api/view/process', { target: '#main-content' });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadInitialView);
    } else {
        loadInitialView();
    }
})();
