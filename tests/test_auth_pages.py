"""Run with an isolated DATABASE_URL; never touches the application database."""
import asyncio
import os
import re
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
from app.core import repository as repo
from app.core.database import AsyncSessionLocal, engine
from app.core.models import User
from app.core.security import hash_password
from app.core.state import AnalysisState

ADMIN = {'email': 'admin@akirs.local', 'password': 'test-only-password-123'}

ANALYSIS_HEADERS = ['Account', 'Amount', 'Direction', 'Credit', 'Debit']


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
        assert client.get('/app/process').status_code == 200
        shell = client.get('/app/process').text
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


def test_every_tab_has_its_own_refreshable_url():
    tabs = {
        '/app/process': '/api/view/process',
        '/app/cleaned': '/api/view/cleaned',
        '/app/cowork': '/api/cowork/view',
        '/app/analyse': '/api/analyse/view',
        '/app/nuban': '/api/nuban/view',
        '/app/intel': '/api/intel/view',
    }
    with TestClient(app) as client:
        # A bare or unknown /app path lands on the default tab instead of 404ing.
        for path in ['/app', '/app/not-a-tab']:
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 307
            assert response.headers['location'] == '/app/process'

        for path, endpoint in tabs.items():
            shell = client.get(path).text
            slug = path.rsplit('/', 1)[1]
            # The tab is a real link, so a refresh or a copied URL resolves.
            assert f'href="{path}"' in shell, path
            assert f'data-tab="{slug}"' in shell, path
            assert f'data-endpoint="{endpoint}"' in shell, path
            # Exactly one nav item carries the active marker, and it is this tab.
            assert shell.count('aria-current="page"') == 1, path
            assert f'data-active-tab="{slug}"' in shell, path

        # Coworking spaces deep link one level deeper.
        space_shell = client.get('/app/cowork/space-42').text
        assert 'data-active-tab="cowork"' in space_shell
        assert 'data-space-id="space-42"' in space_shell

        # Invite links open the coworking tab so the join has somewhere to land.
        invite = client.get('/cowork/join/abc123').text
        assert 'data-invite-token="abc123"' in invite
        assert 'data-active-tab="cowork"' in invite


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
        # The bare root now canonicalises onto the default tab.
        root = client.get('/', headers=headers, follow_redirects=False)
        assert root.status_code == 307
        assert root.headers['location'] == '/app/process'
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


def test_2fa_setup_secret_is_stable_across_calls():
    """Revisiting the setup screen must not rotate the pending secret, otherwise
    the code from a QR the user already scanned is rejected."""
    with TestClient(app) as client:
        _approved_user('stable2fa@akirs.local')
        challenge = _login_challenge(
            client, {'email': 'stable2fa@akirs.local', 'password': 'UserPass123!'}
        )
        assert challenge['setup_required'] is True
        token = challenge['challenge_token']

        first = client.post('/api/auth/2fa/setup', json={'challenge_token': token})
        second = client.post('/api/auth/2fa/setup', json={'challenge_token': token})
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()['secret'] == second.json()['secret']

        code = pyotp.TOTP(first.json()['secret']).now()
        enable = client.post(
            '/api/auth/2fa/enable', json={'challenge_token': token, 'code': code}
        )
        assert enable.status_code == 200, enable.text


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

            # User 2 should NOT be able to delete user1's file. The endpoint
            # answers 200 (not 204) on purpose: HTMX computes shouldSwap as
            # "status < 400 and status != 204", so a 204 would skip the swap and
            # hx-swap="delete" would leave the deleted card on screen.
            r2_del = client.delete(f'/api/delete/{state.id}', headers=headers2)
            assert r2_del.status_code == 200  # Returns 200 but doesn't delete

            # The file still exists for its owner
            assert _run(repo.get(repo.KIND_FILE, state.id)) is not None
        finally:
            _run(repo.delete(repo.KIND_FILE, state.id))


def _analysis_file(user_id, **config):
    """Persist a Ready analysis file owned by `user_id`, optionally pre-configured."""
    state = AnalysisState()
    state.user_id = user_id
    state.original_filename = 'statement.csv'
    state.saved_path = 'analytics_statement.csv'
    state.headers = list(ANALYSIS_HEADERS)
    state.selected_sheets = ['Sheet1']
    state.header_row_idx = 0
    state.status = 'Ready'
    state.config.update(config)
    _run(repo.put(repo.KIND_ANALYSIS, state))
    return state.id


def _save_config(client, headers, file_id, **fields):
    """Post the config form the way the browser does, with a token in the session."""
    return client.post(
        f'/api/analyse/config/{file_id}', headers=headers, data=fields
    )


def test_analyse_config_offers_an_explicit_amount_mode():
    """Credit/debit used to be three optional dropdowns beside a mandatory
    metric, so a file with only a credit/debit pair could not be saved at all."""
    with TestClient(app) as client:
        _approved_user('amounts@akirs.local')
        _approved_user('amounts@akirs.local')
        _, tokens = _full_login(
            client, {'email': 'amounts@akirs.local', 'password': 'UserPass123!'}
        )
        headers = {'Authorization': f"Bearer {tokens['access_token']}"}
        user_id = _get_user_id('amounts@akirs.local')

        file_id = _analysis_file(user_id)
        form = client.post(
            f'/api/analyse/components/config-form/{file_id}', headers=headers
        ).text

        # Both modes are offered as a real choice, not implied by which dropdown
        # happens to be filled in.
        assert 'name="amount_mode" value="single"' in form
        assert 'name="amount_mode" value="split"' in form
        # Only the active mode's selects are required: metric in single mode,
        # credit + debit in split mode. The 4th hit is the script's selector.
        assert 'What are we measuring?' in form
        assert len(re.findall(r'\sdata-mode-required\s', form)) == 3

        # Saving a split config must reach "Configured" with no metric column.
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='split',
            credit_col='Credit', debit_col='Debit',
            title='X', flow_filter='All', limit='50', keep_columns='Account',
        )
        saved = _run(repo.get(repo.KIND_ANALYSIS, file_id))
        assert saved.status == 'Configured'
        assert saved.config['amount_mode'] == 'split'
        assert saved.config['credit_col'] == 'Credit'
        assert saved.config['debit_col'] == 'Debit'
        assert saved.config['metric_col'] == ''

        # Editing back to single must clear the pair, not keep it lurking.
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='single', metric_col='Amount',
            title='X', flow_filter='All', limit='50', keep_columns='Account',
        )
        saved = _run(repo.get(repo.KIND_ANALYSIS, file_id))
        assert saved.config['amount_mode'] == 'single'
        assert saved.config['metric_col'] == 'Amount'
        assert saved.config['credit_col'] == ''
        assert saved.config['debit_col'] == ''


def test_analyse_config_stays_ready_when_a_mode_is_incomplete():
    """A save missing the columns its chosen mode needs must not claim success."""
    with TestClient(app) as client:
        _approved_user('incomplete@akirs.local')
        _, tokens = _full_login(
            client, {'email': 'incomplete@akirs.local', 'password': 'UserPass123!'}
        )
        headers = {'Authorization': f"Bearer {tokens['access_token']}"}
        user_id = _get_user_id('incomplete@akirs.local')

        # Split mode with only one of the pair selected.
        file_id = _analysis_file(user_id)
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='split', credit_col='Credit',
            title='X', flow_filter='All', limit='50', keep_columns='Account',
        )
        assert _run(repo.get(repo.KIND_ANALYSIS, file_id)).status == 'Ready'

        # Reached Configured once, then broken by an edit: must fall back to Ready
        # so the card stops offering "Generate output" for an unsatisfiable config.
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='split',
            credit_col='Credit', debit_col='Debit',
            title='X', flow_filter='All', limit='50', keep_columns='Account',
        )
        assert _run(repo.get(repo.KIND_ANALYSIS, file_id)).status == 'Configured'
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='single',
            title='X', flow_filter='All', limit='50', keep_columns='Account',
        )
        assert _run(repo.get(repo.KIND_ANALYSIS, file_id)).status == 'Ready'


def test_analyse_config_rejects_a_negative_limit_and_says_so():
    """A negative limit reached the report as [:limit], which sliced from the
    end and printed "TOP -35". It is now refused, and the user is told."""
    with TestClient(app) as client:
        _approved_user('limits@akirs.local')
        _, tokens = _full_login(
            client, {'email': 'limits@akirs.local', 'password': 'UserPass123!'}
        )
        headers = {'Authorization': f"Bearer {tokens['access_token']}"}
        user_id = _get_user_id('limits@akirs.local')

        file_id = _analysis_file(user_id)
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='split',
            credit_col='Credit', debit_col='Debit', limit='-35',
            title='X', flow_filter='All', keep_columns='Account',
        )
        saved = _run(repo.get(repo.KIND_ANALYSIS, file_id))
        # Treated as "no limit" rather than a reversed slice.
        assert saved.config['limit'] is None
        assert 'Limit must be 1 or more' in saved.config['config_error']

        # The correction is surfaced in the re-rendered form, not swallowed.
        form = client.post(
            f'/api/analyse/components/config-form/{file_id}', headers=headers
        ).text
        assert 'Limit must be 1 or more' in form
        assert 'Saved with a correction' in form

        # A valid limit clears the warning again.
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='split',
            credit_col='Credit', debit_col='Debit', limit='35',
            title='X', flow_filter='All', keep_columns='Account',
        )
        saved = _run(repo.get(repo.KIND_ANALYSIS, file_id))
        assert saved.config['limit'] == 35
        assert 'config_error' not in saved.config


def test_analyse_config_defaults_the_movement_register_to_the_nuban_column():
    """Keying the register by name would pool accounts that only share a name."""
    with TestClient(app) as client:
        _approved_user('register@akirs.local')
        _, tokens = _full_login(
            client, {'email': 'register@akirs.local', 'password': 'UserPass123!'}
        )
        headers = {'Authorization': f"Bearer {tokens['access_token']}"}
        user_id = _get_user_id('register@akirs.local')

        file_id = _analysis_file(user_id)
        _save_config(
            client, headers, file_id,
            identity_col='Account', amount_mode='split',
            credit_col='Credit', debit_col='Debit', nuban_col='NUBAN',
            movement_threshold='100,000,000', movement_sort='largest',
            title='X', flow_filter='All', keep_columns='Account',
        )
        saved = _run(repo.get(repo.KIND_ANALYSIS, file_id))
        assert saved.config['movement_threshold'] == 100_000_000.0
        assert saved.config['movement_sort'] == 'largest'
        # Falls back to the NUBAN column rather than grouping by name.
        assert saved.config['movement_identity_col'] == 'NUBAN'

        form = client.post(
            f'/api/analyse/components/config-form/{file_id}', headers=headers
        ).text
        assert 'Movement register' in form
        assert '100,000,000' in form


def test_analyse_config_infers_the_mode_for_configs_saved_before_it_existed():
    with TestClient(app) as client:
        _approved_user('legacy@akirs.local')
        _, tokens = _full_login(
            client, {'email': 'legacy@akirs.local', 'password': 'UserPass123!'}
        )
        headers = {'Authorization': f"Bearer {tokens['access_token']}"}
        user_id = _get_user_id('legacy@akirs.local')

        file_id = _analysis_file(
            user_id,
            identity_col='Account', credit_col='Credit', debit_col='Debit',
        )
        form = client.post(
            f'/api/analyse/components/config-form/{file_id}', headers=headers
        ).text
        # The split panel is the one shown, so the user is not silently switched.
        assert 'value="split" checked' in form
        assert 'name="amount_mode" value="single"' in form


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

