"""Guards the reverse-proxy scheme handling that broke the admin UI in production.

Behind Coolify/Traefik, uvicorn only honours X-Forwarded-Proto when the proxy's
connecting IP is in FORWARDED_ALLOW_IPS (default "127.0.0.1,::1"). Traefik lives
on the coolify docker network, so without an explicit --forwarded-allow-ips the
header was dropped and request.url.scheme stayed "http". Every url_for and
redirect was then emitted as http://, which the browser blocked as mixed active
content and which made the admin password form post over plaintext HTTP.

These tests fail if that regresses.
"""
"""Run with an isolated DATABASE_URL; never touches the application database."""
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
os.environ['CLEANUP_ENABLED'] = 'false'

import re

from fastapi.testclient import TestClient

from main import app

START_SH = Path(__file__).resolve().parents[1] / 'scripts' / 'start.sh'

HOST = 'toolkit.akirs.ak.gov.ng'


def _absolute_urls(html: str) -> list[str]:
    return [u for u in re.findall(r'https?://[^\s"\'<>]+', html)
            if 'w3.org' not in u]


def test_start_script_trusts_forwarded_headers():
    """The web server must accept X-Forwarded-* from the proxy.

    gunicorn defaults forwarded_allow_ips to 127.0.0.1,::1, which silently
    disables ProxyHeadersMiddleware for any non-loopback proxy.
    """
    body = START_SH.read_text(encoding='utf-8')

    assert '--forwarded-allow-ips' in body, (
        'scripts/start.sh no longer passes --forwarded-allow-ips to gunicorn. '
        'The proxy is not on loopback, so X-Forwarded-Proto will be ignored and '
        'every generated URL will revert to http://.'
    )

    # Guard against a value that only trusts loopback again.
    assert re.search(r'--forwarded-allow-ips\s+"?\$\{FORWARDED_ALLOW_IPS:-\*', body), (
        'FORWARDED_ALLOW_IPS must default to "*" (or the proxy subnet), not '
        'loopback. The web port is only "expose"d on the coolify network, so the '
        'proxy is the sole client.'
    )


def test_admin_assets_are_not_insecure_when_served_over_https():
    """No http:// asset or form action may appear on an HTTPS admin page."""
    with TestClient(app, base_url=f'https://{HOST}') as client:
        response = client.get('/admin/login', follow_redirects=True)
        assert response.status_code == 200, response.text

        html = response.text
        assert f'action="https://{HOST}/admin/login"' in html

        insecure = [u for u in _absolute_urls(html) if u.startswith('http://')]
        assert not insecure, (
            f'admin page rendered {len(insecure)} insecure URL(s), e.g. {insecure[:3]}. '
            'These are blocked as mixed content by the browser.'
        )


def test_admin_redirects_stay_on_https():
    """The /admin -> /admin/ redirect must not downgrade to http."""
    with TestClient(app, base_url=f'https://{HOST}') as client:
        response = client.get('/admin', follow_redirects=False)

        assert response.status_code in (301, 302, 303, 307, 308)
        location = response.headers['location']
        assert location.startswith('https://'), (
            f'/admin redirected to {location!r}; scheme downgraded.'
        )