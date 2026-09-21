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

    // Superusers get quick links to the Starlette Admin dashboard (separate login).
    async function revealAdminLinks() {
        try {
            const response = await auth.apiFetch('/api/auth/me');
            if (!response.ok) return;
            const me = await response.json();
            if (me.is_superuser) {
                const links = document.getElementById('admin-links');
                if (links) links.style.display = 'flex';
            }
        } catch (error) {
            /* non-superusers and offline users simply keep the links hidden */
        }
    }

    function loadInitialView() {
        revealAdminLinks();
        if (window.htmx) window.htmx.ajax('GET', '/api/view/process', { target: '#main-content' });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadInitialView);
    } else {
        loadInitialView();
    }
})();
