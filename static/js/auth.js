(() => {
    'use strict';
    const message = document.getElementById('auth-message');
    const screens = ['account', 'verify', 'setup', 'pending', 'mfa'];
    const routeScreen = location.pathname.split('/')[2] || 'account';
    const screen = screens.includes(routeScreen) ? routeScreen : 'account';
    document.querySelectorAll('[data-screen]').forEach(section => {
        section.hidden = section.dataset.screen !== screen;
    });
    function showMessage(text, kind = 'error') {
        message.textContent = text;
        message.dataset.kind = kind;
        message.hidden = false;
    }
    function selectTab(signup) {
        ['login', 'signup'].forEach(name => {
            const selected = (name === 'signup') === signup;
            const tab = document.getElementById(`${name}-tab`);
            tab.setAttribute('aria-selected', String(selected));
            tab.tabIndex = selected ? 0 : -1;
            document.getElementById(`${name}-panel`).hidden = !selected;
            document.getElementById(`${name}-instructions`).hidden = !selected || screen !== 'account';
        });
        message.hidden = true;
    }
    document.getElementById('login-tab').addEventListener('click', () => selectTab(false));
    document.getElementById('signup-tab').addEventListener('click', () => selectTab(true));
    document.querySelector('.auth-tabs').addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const signup = event.key === 'End' || (event.key !== 'Home' && document.getElementById('login-tab').getAttribute('aria-selected') === 'true');
        selectTab(signup);
        document.getElementById(signup ? 'signup-tab' : 'login-tab').focus();
    });
    selectTab(new URLSearchParams(location.search).get('mode') === 'signup');
    document.querySelectorAll('.auth-password button[aria-controls]').forEach(button => {
        button.addEventListener('click', () => {
            const input = document.getElementById(button.getAttribute('aria-controls'));
            const visible = input.type === 'password';
            input.type = visible ? 'text' : 'password';
            button.textContent = visible ? 'Hide' : 'Show';
            button.setAttribute('aria-pressed', String(visible));
            const field = input.id === 'login-password' ? 'login' : 'confirmation';
            button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${field} password`);
        });
    });
    document.getElementById('login-form').addEventListener('submit', async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type=submit]');
        button.disabled = true;
        button.textContent = 'Logging in…';
        message.hidden = true;
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(Object.fromEntries(new FormData(form)))
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check your email and password and try again.');
            }
            // The server stores the access token in an HttpOnly cookie so normal
            // navigation, HTMX requests and download links all authenticate.
            form.reset();
            location.replace('/');
        } catch (error) {
            showMessage(error instanceof TypeError ? 'Unable to connect. Check your connection and try again.' : error.message);
        } finally {
            button.disabled = false;
            button.textContent = 'Log in to workspace';
        }
    });
    const confirmation = document.getElementById('confirm-password');
    function validatePasswords() {
        confirmation.setCustomValidity(confirmation.value !== document.getElementById('signup-password').value ? 'Passwords must match.' : '');
    }
    confirmation.addEventListener('input', validatePasswords);
    document.getElementById('signup-password').addEventListener('input', validatePasswords);
    const unavailable = {
        'signup-form': 'Account registration is not available yet. Please contact your administrator for access.',
        'verify-form': 'Email verification is not available yet. Please contact your administrator.',
        'setup-form': 'Authenticator setup is not available yet. Please contact your administrator.',
        'mfa-form': 'Authenticator login is not available yet. Please return to the login page.'
    };
    Object.entries(unavailable).forEach(([id, text]) => {
        document.getElementById(id).addEventListener('submit', event => {
            event.preventDefault();
            showMessage(text);
        });
    });
    document.getElementById('resend-code').addEventListener('click', () => showMessage('Verification emails are not available yet. Please contact your administrator.'));
    document.getElementById('copy-key').disabled = true;
    document.getElementById('setup-key').placeholder = 'Setup key is not available yet';
    if (screen !== 'account') showMessage('This account step is not available yet. Please contact your administrator for access.');
})();
