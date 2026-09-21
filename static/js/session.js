(() => {
    const logout = document.getElementById('logout-button');
    logout?.addEventListener('click', async () => {
        logout.disabled = true;
        try {
            const response = await fetch('/api/auth/logout', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({all_devices: true})
            });
            if (!response.ok && response.status !== 401) throw new Error('Logout failed');
            location.replace('/auth');
        } catch {
            logout.disabled = false;
            window.alert('Unable to log out. Please try again.');
        }
    });
    document.addEventListener('htmx:responseError', event => {
        if (event.detail.xhr.status === 401) location.replace('/auth');
    });
})();
