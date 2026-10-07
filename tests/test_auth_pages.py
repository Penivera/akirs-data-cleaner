"""Run with an isolated DATABASE_URL; never touches the application database."""
import asyncio
import os
import tempfile
from pathlib import Path

_test_dir = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_dir.name) / 'test.db')
os.environ['APP_ENV'] = 'development'
os.environ['ADMIN_PASSWORD'] = 'test-only-password-123'
os.environ['SECRET_KEY'] = 'test-only-secret-key-at-least-32-characters'
os.environ['DEBUG'] = 'false'
os.environ['ADMIN_EMAIL'] = 'admin@akirs.local'
# Disable the startup cleanup job so tests never touch the working directory's
# uploads/cleaned/reports folders.
os.environ['CLEANUP_ENABLED'] = 'false'

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from app.core.database import AsyncSessionLocal, engine
from app.core.models import User
from app.core.security import hash_password

ADMIN = {'email': 'admin@akirs.local', 'password': 'test-only-password-123'}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope='module', autouse=True)
def _cleanup_database():
    yield
    _run(engine.dispose())
    _test_dir.cleanup()


def _approved_user(email, password='UserPass123!'):
    """Insert an already-approved user directly, so tests do not depend on order."""
    async def _insert():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            if result.scalars().first() is None:
                db.add(
                    User(
                        email=email,
                        full_name=email,
                        hashed_password=hash_password(password),
                        is_active=True,
                        is_approved=True,
                    )
                )
                await db.commit()

    _run(_insert())


def _get_user_id(email):
    async def _fetch():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalars().first()
            return user.id if user is not None else None

    return _run(_fetch())


def _approve_user(email):
    async def _update():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalars().first()
            user.is_approved = True
            await db.commit()

    _run(_update())


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
    assert setup.json()['qr_svg'].startswith('data:image/svg+xml')
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
        assert client.get('/app').status_code == 200
        shell = client.get('/app').text
        assert '/static/js/auth-core.js' in shell
        assert '/static/js/session.js' in shell
        assert 'id="main-content"' in shell
        assert 'id="admin-link"' in shell
        assert 'href="/admin"' in shell
        auth_page = client.get('/auth').text
        assert 'id="login-form"' in auth_page and 'id="setup-form"' in auth_page
        assert 'id="setup-qr"' in auth_page
        assert '/static/js/auth-core.js' in auth_page
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
        _approve_user('signup@akirs.local')

        challenge = _login_challenge(
            client, {'email': 'signup@akirs.local', 'password': 'UserPass123!'}
        )
        assert challenge['setup_required'] is True
        secret, tokens = _complete_setup(client, challenge['challenge_token'])
        assert 'recovery_codes' not in tokens

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


def test_user_data_isolation():
    """Verify that users cannot see or access each other's files."""
    import time as _time

    from app.core import repository as repo
    from app.core.state import FileState

    with TestClient(app) as client:
        # Create two users
        _approved_user('user1@akirs.local')
        _approved_user('user2@akirs.local')

        _, tokens1 = _full_login(
            client, {'email': 'user1@akirs.local', 'password': 'UserPass123!'}
        )
        _, tokens2 = _full_login(
            client, {'email': 'user2@akirs.local', 'password': 'UserPass123!'}
        )

        headers1 = {'Authorization': f"Bearer {tokens1['access_token']}"}
        headers2 = {'Authorization': f"Bearer {tokens2['access_token']}"}

        user1_id = _get_user_id('user1@akirs.local')

        # User 1 should see no files initially
        r1 = client.get('/api/view/process', headers=headers1)
        assert r1.status_code == 200

        # User 2 should also see no files initially
        r2 = client.get('/api/view/process', headers=headers2)
        assert r2.status_code == 200

        # Simulate a file owned by user1, persisted through the repository
        state = FileState()
        state.user_id = user1_id
        state.original_filename = 'user1_file.xlsx'
        state.uploaded_at = _time.time()
        _run(repo.put(repo.KIND_FILE, state))

        try:
            # User 1 should see their file
            r1 = client.get('/api/view/process', headers=headers1)
            assert 'user1_file.xlsx' in r1.text

            # User 2 should NOT see user1's file
            r2 = client.get('/api/view/process', headers=headers2)
            assert 'user1_file.xlsx' not in r2.text

            # User 2 should NOT be able to access user1's file directly
            r2_view = client.get(f'/api/view/{state.id}', headers=headers2)
            assert r2_view.text == 'Not available'

            # User 2 should NOT be able to delete user1's file
            r2_del = client.delete(f'/api/delete/{state.id}', headers=headers2)
            assert r2_del.status_code == 204  # Returns 204 but doesn't delete

            # The file still exists for its owner
            assert _run(repo.get(repo.KIND_FILE, state.id)) is not None
        finally:
            _run(repo.delete(repo.KIND_FILE, state.id))


def test_repository_roundtrip_tasks_and_purge():
    """State survives a JSON round-trip through the database, background tasks
    are readable/updatable, and the purge job removes stale rows."""
    import time as _time

    from app.core import repository as repo
    from app.core.state import FileState

    _approved_user('repo@akirs.local')
    uid = _get_user_id('repo@akirs.local')

    state = FileState()
    state.user_id = uid
    state.original_filename = 'roundtrip.xlsx'
    state.uploaded_at = _time.time()
    state.status = 'Needs Duplicate Review (2 groups)'
    state.mapped_fields = {'NUBAN': 'ACCT_NO', 'ACCOUNT_NAME': ['FIRST', 'LAST']}
    state.field_separators = {'ACCOUNT_NAME': ' '}
    state.extracted_records = [{'id': 's0r2', 'values': ['a', 'b']}]
    state.duplicate_groups = [{'nuban': '123', 'records': [{'id': 's0r2'}]}]
    state.health_report = {'score': 90, 'issues': [{'severity': 'WARNING'}]}
    _run(repo.put(repo.KIND_FILE, state))
    try:
        loaded = _run(repo.get(repo.KIND_FILE, state.id))
        assert loaded is not None
        assert loaded.original_filename == 'roundtrip.xlsx'
        assert loaded.user_id == uid
        assert loaded.mapped_fields == {'NUBAN': 'ACCT_NO', 'ACCOUNT_NAME': ['FIRST', 'LAST']}
        assert loaded.field_separators == {'ACCOUNT_NAME': ' '}
        assert loaded.extracted_records[0]['values'] == ['a', 'b']
        assert loaded.duplicate_groups[0]['records'][0]['id'] == 's0r2'
        assert loaded.health_report['score'] == 90

        listed_ids = {s.id for s in _run(repo.list_for_user(repo.KIND_FILE, uid))}
        assert state.id in listed_ids
    finally:
        _run(repo.delete(repo.KIND_FILE, state.id))
    assert _run(repo.get(repo.KIND_FILE, state.id)) is None

    # Background task lifecycle
    _run(repo.set_task('proc_test', state.id, uid, 'processing', 'Starting...'))
    try:
        task = _run(repo.get_task('proc_test'))
        assert task == {
            'status': 'processing',
            'file_id': state.id,
            'user_id': uid,
            'message': 'Starting...',
        }
        _run(repo.update_task('proc_test', message='Working...', status='done'))
        task = _run(repo.get_task('proc_test'))
        assert task['status'] == 'done' and task['message'] == 'Working...'
    finally:
        _run(repo.purge_older_than(_time.time() + 1))

    # Purge removes items uploaded before the cutoff
    stale = FileState()
    stale.user_id = uid
    stale.original_filename = 'stale.xlsx'
    stale.uploaded_at = 0.0
    _run(repo.put(repo.KIND_FILE, stale))
    assert _run(repo.purge_older_than(_time.time())) >= 1
    assert _run(repo.get(repo.KIND_FILE, stale.id)) is None
