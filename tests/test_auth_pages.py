"""Run with an isolated DATABASE_URL; never touches the application database."""
import os
import tempfile
from pathlib import Path

_test_dir = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_dir.name) / 'test.db')
os.environ['ADMIN_PASSWORD'] = 'test-only-password-123'
os.environ['SECRET_KEY'] = 'test-only-secret-key-at-least-32-characters'
os.environ['DEBUG'] = 'false'
os.environ['ADMIN_EMAIL'] = 'admin@akirs.local'

import pyotp
import pytest
from fastapi.testclient import TestClient

from main import app
from app.core.database import SessionLocal, engine
from app.core.models import User
from app.core.security import hash_password

ADMIN = {'email': 'admin@akirs.local', 'password': 'test-only-password-123'}


@pytest.fixture(scope='module', autouse=True)
def _cleanup_database():
    yield
    engine.dispose()
    _test_dir.cleanup()


def _approved_user(email, password='UserPass123!'):
    """Insert an already-approved user directly, so tests do not depend on order."""
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first() is None:
            db.add(
                User(
                    email=email,
                    full_name=email,
                    hashed_password=hash_password(password),
                    is_active=True,
                    is_approved=True,
                )
            )
            db.commit()
    finally:
        db.close()


def _login_challenge(client, credentials):
    response = client.post('/api/auth/login', json=credentials)
    assert response.status_code == 200, response.text
    body = response.json()
    assert 'challenge_token' in body
    assert 'set-cookie' not in response.headers
    return body


def _complete_setup(client, challenge):
    setup = client.post('/api/auth/2fa/setup', json={'challenge_token': challenge})
    assert setup.status_code == 200, setup.text
    secret = setup.json()['secret']
    assert setup.json()['otpauth_url'].startswith('otpauth://')
    code = pyotp.TOTP(secret).now()
    enable = client.post(
        '/api/auth/2fa/enable', json={'challenge_token': challenge, 'code': code}
    )
    assert enable.status_code == 200, enable.text
    return secret, enable.json()


def _full_login(client, credentials):
    challenge = _login_challenge(client, credentials)
    assert challenge['setup_required'] is True
    secret, tokens = _complete_setup(client, challenge['challenge_token'])
    return secret, tokens


def test_account_pages_are_public_and_workspace_requires_login():
    with TestClient(app) as client:
        for path in ['/auth', '/auth/verify', '/auth/setup', '/auth/pending', '/auth/mfa']:
            response = client.get(path)
            assert response.status_code == 200
            assert 'Cache-Control' in response.headers
        response = client.get('/', headers={'Accept': 'text/html'}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/auth'
        assert client.get('/api/auth/me').status_code == 401


def test_signup_then_admin_approval_then_mandatory_2fa():
    with TestClient(app) as client:
        signup = client.post(
            '/api/auth/signup',
            json={
                'email': 'signup@akirs.local',
                'password': 'UserPass123!',
                'full_name': 'Sign Up',
            },
        )
        assert signup.status_code == 201, signup.text

        # Cannot log in until approved.
        pending = client.post(
            '/api/auth/login',
            json={'email': 'signup@akirs.local', 'password': 'UserPass123!'},
        )
        assert pending.status_code == 403

        # Admin approves.
        db = SessionLocal()
        user = db.query(User).filter(User.email == 'signup@akirs.local').first()
        user.is_approved = True
        db.commit()
        db.close()

        challenge = _login_challenge(
            client, {'email': 'signup@akirs.local', 'password': 'UserPass123!'}
        )
        assert challenge['setup_required'] is True
        secret, tokens = _complete_setup(client, challenge['challenge_token'])
        assert len(tokens['recovery_codes']) == 10

        headers = {'Authorization': f"Bearer {tokens['access_token']}"}
        assert client.get('/api/auth/me', headers=headers).status_code == 200
        assert client.get('/api/view/process', headers=headers).status_code == 200
        assert client.get('/', headers=headers).status_code == 200

        # A later login requires the second factor.
        challenge2 = _login_challenge(
            client, {'email': 'signup@akirs.local', 'password': 'UserPass123!'}
        )
        assert challenge2['mfa_required'] is True
        verify = client.post(
            '/api/auth/2fa/verify',
            json={
                'challenge_token': challenge2['challenge_token'],
                'code': pyotp.TOTP(secret).now(),
            },
        )
        assert verify.status_code == 200, verify.text
        assert client.get('/api/auth/me').status_code == 401


def test_htmx_redirect_and_cross_origin_rejection():
    with TestClient(app) as client:
        response = client.get('/api/view/process', headers={'HX-Request': 'true'})
        assert response.status_code == 401
        assert response.headers['HX-Redirect'] == '/auth'

        _approved_user('htmx@akirs.local')
        _, tokens = _full_login(
            client, {'email': 'htmx@akirs.local', 'password': 'UserPass123!'}
        )
        headers = {'Authorization': f"Bearer {tokens['access_token']}"}

        cross_origin = client.post(
            '/api/auth/logout',
            json={'all_devices': True},
            headers={**headers, 'Origin': 'https://evil.example'},
        )
        assert cross_origin.status_code == 403

        assert (
            client.post(
                '/api/auth/logout', json={'all_devices': True}, headers=headers
            ).status_code
            == 204
        )
        assert client.get('/api/auth/me', headers=headers).status_code == 401
