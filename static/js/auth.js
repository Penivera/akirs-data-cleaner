(() => {
    'use strict';
    const auth = window.AKIRSAuth;
    const message = document.getElementById('auth-message');
<<<<<<< HEAD
    const screens = ['account', 'setup', 'mfa', 'pending'];
=======
    const screens = ['account', 'setup', 'mfa', 'pending', 'recovery'];
    // Mirrors the challenge for the session so a reload on /auth/mfa can still
    // decide whether to show the "use a recovery code" toggle.
    const RECOVERY_FLAG_KEY = 'akirs_recovery_available';
>>>>>>> 7def6beb69aa244278b22f5b25ebc9ba8d1329f6

    function showMessage(text, kind = 'error') {
        message.textContent = text;
        message.dataset.kind = kind;
        message.hidden = false;
    }
    function hideMessage() { message.hidden = true; }

    function showScreen(name) {
        screens.forEach((key) => {
            const section = document.querySelector(`[data-screen="${key}"]`);
            if (section) section.hidden = key !== name;
        });
        const path = name === 'account' ? '/auth' : `/auth/${name}`;
        history.replaceState(null, '', path);
        hideMessage();
    }

    function currentScreen() {
        const route = location.pathname.split('/')[2] || 'account';
        return screens.includes(route) ? route : 'account';
    }

    function setBusy(button, busy, label) {
        if (!button) return;
        button.disabled = busy;
        if (label) button.textContent = busy ? 'Please wait…' : label;
    }

    async function postJSON(url, body) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await response.json().catch(() => ({}));
        return { response, data };
    }

    // --- Tabs -----------------------------------------------------------------
    function selectTab(signup) {
        ['login', 'signup'].forEach((name) => {
            const selected = (name === 'signup') === signup;
            const tab = document.getElementById(`${name}-tab`);
            tab.setAttribute('aria-selected', String(selected));
            tab.tabIndex = selected ? 0 : -1;
            document.getElementById(`${name}-panel`).hidden = !selected;
            const instructions = document.getElementById(`${name}-instructions`);
            if (instructions) instructions.hidden = !selected || currentScreen() !== 'account';
        });
        hideMessage();
    }
    document.getElementById('login-tab').addEventListener('click', () => selectTab(false));
    document.getElementById('signup-tab').addEventListener('click', () => selectTab(true));
    document.querySelector('.auth-tabs').addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const signup = event.key === 'End'
            || (event.key !== 'Home' && document.getElementById('login-tab').getAttribute('aria-selected') === 'true');
        selectTab(signup);
        document.getElementById(signup ? 'signup-tab' : 'login-tab').focus();
    });
    selectTab(new URLSearchParams(location.search).get('mode') === 'signup');

    // --- Password confirmation ------------------------------------------------
    const confirmation = document.getElementById('confirm-password');
    function validatePasswords() {
        confirmation.setCustomValidity(
            confirmation.value !== document.getElementById('signup-password').value
                ? 'Passwords must match.'
                : ''
        );
    }
    confirmation.addEventListener('input', validatePasswords);
    document.getElementById('signup-password').addEventListener('input', validatePasswords);

    // --- Password reveal buttons (login + confirmation) -----------------------
    document.querySelectorAll('.auth-password button[aria-controls]').forEach((button) => {
        button.addEventListener('click', () => {
            const input = document.getElementById(button.getAttribute('aria-controls'));
            if (!input) return;
            const visible = input.type === 'password';
            input.type = visible ? 'text' : 'password';
            button.textContent = visible ? 'Hide' : 'Show';
            button.setAttribute('aria-pressed', String(visible));
            const field = input.id === 'login-password' ? 'login' : 'confirmation';
            button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${field} password`);
        });
    });

    // --- Login -----------------------------------------------------------------
    document.getElementById('login-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type=submit]');
        hideMessage();
        setBusy(button, true, 'Log in to workspace');
        try {
            const { response, data } = await postJSON('/api/auth/login', {
                email: form.email.value,
                password: form.password.value,
            });
            if (response.status === 403 && /pending/i.test(data.detail || '')) {
                showScreen('pending');
                return;
            }
            if (!response.ok) {
                showMessage(typeof data.detail === 'string'
                    ? data.detail
                    : 'Please check your email and password and try again.');
                return;
            }
            auth.setChallenge(data.challenge_token);
            sessionStorage.setItem(RECOVERY_FLAG_KEY, data.recovery_codes_available ? '1' : '0');
            form.reset();
            if (data.setup_required) {
                await beginSetup();
            } else {
                setRecoveryOption(data.recovery_codes_available === true);
                showScreen('mfa');
            }
        } catch (error) {
            showMessage('Unable to connect. Check your connection and try again.');
        } finally {
            setBusy(button, false, 'Log in to workspace');
        }
    });

    // --- Signup ----------------------------------------------------------------
    document.getElementById('signup-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type=submit]');
        hideMessage();
        setBusy(button, true, 'Create account');
        try {
            const { response, data } = await postJSON('/api/auth/signup', {
                full_name: form.full_name.value,
                email: form.email.value,
                password: form.password.value,
            });
            if (response.status === 201) {
                form.reset();
                showScreen('pending');
                return;
            }
            showMessage(typeof data.detail === 'string'
                ? data.detail
                : 'We could not create your account. Please check your details.');
        } catch (error) {
            showMessage('Unable to connect. Check your connection and try again.');
        } finally {
            setBusy(button, false, 'Create account');
        }
    });

    // --- Two-factor setup ------------------------------------------------------
    const setupKey = document.getElementById('setup-key');
    const copyKey = document.getElementById('copy-key');
    copyKey.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(setupKey.value);
            copyKey.textContent = 'Copied';
            setTimeout(() => { copyKey.textContent = 'Copy'; }, 1500);
        } catch (error) {
            setupKey.select();
            document.execCommand('copy');
        }
    });

    async function beginSetup() {
        if (!auth.challenge) { showScreen('account'); return; }
        const { response, data } = await postJSON('/api/auth/2fa/setup', {
            challenge_token: auth.challenge,
        });
        if (!response.ok) {
            auth.clearChallenge();
            showScreen('account');
            showMessage(typeof data.detail === 'string' ? data.detail : 'Please log in again.');
            return;
        }
        setupKey.value = data.secret;
        setupKey.placeholder = '';
        copyKey.disabled = false;
        const qr = document.getElementById('setup-qr');
        if (data.qr_svg) {
            qr.src = data.qr_svg;
            qr.hidden = false;
        } else {
            qr.removeAttribute('src');
            qr.hidden = true;
        }
        showScreen('setup');
    }

    document.getElementById('setup-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type=submit]');
        hideMessage();
        setBusy(button, true, 'Connect authenticator');
        try {
            const { response, data } = await postJSON('/api/auth/2fa/enable', {
                challenge_token: auth.challenge,
                code: form.code.value,
            });
            if (!response.ok) {
                showMessage(typeof data.detail === 'string' ? data.detail : 'That code is not valid. Try again.');
                return;
            }
            const recoveryCodes = data.recovery_codes || [];
            auth.setTokens(data.access_token, data.refresh_token);
            auth.clearChallenge();
            form.reset();
<<<<<<< HEAD
            auth.redirectToWorkspace();
=======
            if (recoveryCodes.length) {
                showRecoveryCodes(recoveryCodes);
            } else {
                // No recovery codes configured (RECOVERY_CODE_COUNT=0): skip the screen.
                auth.redirectToWorkspace();
            }
>>>>>>> 7def6beb69aa244278b22f5b25ebc9ba8d1329f6
        } catch (error) {
            showMessage('Unable to connect. Check your connection and try again.');
        } finally {
            setBusy(button, false, 'Connect authenticator');
        }
    });

    // --- Two-factor verification ----------------------------------------------
<<<<<<< HEAD
=======
    const recoveryRow = document.getElementById('mfa-recovery-row');
    const mfaCodeField = document.getElementById('mfa-code').closest('.auth-field');
    const mfaCodeInput = document.getElementById('mfa-code');
    const recoveryCodeInput = document.getElementById('recovery-code');
    const useRecoveryButton = document.getElementById('use-recovery');

    // Reset the MFA form to authenticator-code mode. When the account has no
    // unused recovery codes, hide the toggle entirely so users cannot attempt a
    // code that can never succeed.
    function setRecoveryOption(available) {
        recoveryRow.hidden = true;
        mfaCodeField.hidden = false;
        mfaCodeInput.required = true;
        recoveryCodeInput.required = false;
        recoveryCodeInput.value = '';
        useRecoveryButton.textContent = 'Use a recovery code instead';
        useRecoveryButton.hidden = !available;
    }

    useRecoveryButton.addEventListener('click', (event) => {
        event.preventDefault();
        const showing = !recoveryRow.hidden;
        recoveryRow.hidden = showing;
        mfaCodeField.hidden = !showing;
        mfaCodeInput.required = !showing;
        recoveryCodeInput.required = showing;
        event.currentTarget.textContent = showing
            ? 'Use a recovery code instead'
            : 'Use an authenticator code';
    });

>>>>>>> 7def6beb69aa244278b22f5b25ebc9ba8d1329f6
    document.getElementById('mfa-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type=submit]');
        hideMessage();
        setBusy(button, true, 'Log in to workspace');
        try {
            const payload = { challenge_token: auth.challenge, code: form.code.value };
            const { response, data } = await postJSON('/api/auth/2fa/verify', payload);
            if (!response.ok) {
                showMessage(typeof data.detail === 'string' ? data.detail : 'That code is not valid. Try again.');
                return;
            }
            auth.setTokens(data.access_token, data.refresh_token);
            auth.clearChallenge();
            form.reset();
            auth.redirectToWorkspace();
        } catch (error) {
            showMessage('Unable to connect. Check your connection and try again.');
        } finally {
            setBusy(button, false, 'Log in to workspace');
        }
    });

    document.getElementById('pending-login').addEventListener('click', (event) => {
        event.preventDefault();
        showScreen('account');
    });

    // --- Boot ------------------------------------------------------------------
    if (auth.isAuthed() && currentScreen() === 'account') {
        auth.redirectToWorkspace();
    } else {
        const screen = currentScreen();
        if ((screen === 'setup' || screen === 'mfa') && !auth.challenge) {
            showScreen('account');
            showMessage('Please log in to continue.');
        } else if (screen === 'setup') {
            beginSetup();
        } else {
            if (screen === 'mfa') {
                setRecoveryOption(sessionStorage.getItem(RECOVERY_FLAG_KEY) === '1');
            }
            showScreen(screen);
        }
    }
})();
