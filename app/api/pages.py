"""Public account pages and the cookie-free workspace shell."""
from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _asset_version(path: str) -> str:
    """Short content hash so cached JS/CSS is busted whenever a file changes."""
    try:
        return sha256(Path(path).read_bytes()).hexdigest()[:12]
    except OSError:
        return "0"


@router.get('/auth', response_class=HTMLResponse)
@router.get('/auth/verify', response_class=HTMLResponse)
@router.get('/auth/setup', response_class=HTMLResponse)
@router.get('/auth/pending', response_class=HTMLResponse)
@router.get('/auth/mfa', response_class=HTMLResponse)
@router.get('/auth/recovery', response_class=HTMLResponse)
def auth_page(request: Request):
    versions = {
        'auth_js': _asset_version('static/js/auth.js'),
        'auth_core_js': _asset_version('static/js/auth-core.js'),
        'auth_css': _asset_version('static/css/auth.css'),
    }
    return templates.TemplateResponse(
        request=request, name='auth.html', context={'asset_versions': versions}
    )


@router.get('/app', response_class=HTMLResponse)
def workspace_page(request: Request):
    """Public shell with no data; the guarded JS loads content with the bearer token."""
    return templates.TemplateResponse(request=request, name='index.html')
