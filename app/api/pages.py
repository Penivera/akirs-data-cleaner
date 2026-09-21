"""Public account pages, separate from the protected workspace routers."""
from hashlib import sha256
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get('/auth', response_class=HTMLResponse)
@router.get('/auth/verify', response_class=HTMLResponse)
@router.get('/auth/setup', response_class=HTMLResponse)
@router.get('/auth/pending', response_class=HTMLResponse)
@router.get('/auth/mfa', response_class=HTMLResponse)
def auth_page(request: Request):
    # Keep updated templates and tab behavior together even with cached assets.
    versions = {
        name: sha256(Path(path).read_bytes()).hexdigest()[:12]
        for name, path in {
            'auth_js': 'static/js/auth.js',
            'auth_css': 'static/css/auth.css',
        }.items()
    }
    return templates.TemplateResponse(
        request=request, name='auth.html', context={'asset_versions': versions}
    )
