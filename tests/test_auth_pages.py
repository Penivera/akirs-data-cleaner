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

from fastapi.testclient import TestClient
from main import app


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


def test_browser_login_workspace_and_logout():
    with TestClient(app) as client:
        assert client.post('/api/auth/login', json={'email': 'admin@akirs.local', 'password': 'wrong'}).status_code == 401
        response = client.post('/api/auth/login', json={'email': 'admin@akirs.local', 'password': 'test-only-password-123'})
        assert response.status_code == 200
        assert 'HttpOnly' in response.headers['set-cookie']
        assert 'SameSite=strict' in response.headers['set-cookie']
        token = response.json()['access_token']
        assert client.get('/').status_code == 200
        assert client.get('/api/auth/me').status_code == 200
        assert client.get('/api/view/process').status_code == 200
        assert client.post('/api/auth/logout', json={'all_devices': True}, headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/auth/logout', json={'all_devices': True}).status_code == 204
        assert 'akirs_access' not in client.cookies
        assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401


def test_bearer_clients_and_expired_browser_session():
    with TestClient(app) as client:
        response = client.post('/api/auth/login', json={'email': 'admin@akirs.local', 'password': 'test-only-password-123'})
        token = response.json()['access_token']
        client.cookies.clear()
        assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'}).status_code == 200
        response = client.get('/api/view/process', headers={'HX-Request': 'true'})
        assert response.status_code == 401
        assert response.headers['HX-Redirect'] == '/auth'
        client.cookies.set('akirs_access', 'invalid')
        assert client.get('/', headers={'Accept': 'text/html'}, follow_redirects=False).status_code == 303
