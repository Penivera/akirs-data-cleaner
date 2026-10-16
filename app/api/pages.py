"""Public account pages and the cookie-free workspace shell."""
from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
def auth_page(request: Request):
    versions = {
        'auth_js': _asset_version('static/js/auth.js'),
        'auth_core_js': _asset_version('static/js/auth-core.js'),
        'auth_css': _asset_version('static/css/auth.css'),
    }
    return templates.TemplateResponse(
        request=request, name='auth.html', context={'asset_versions': versions}
    )


#: Canonical slug for each primary navigation tab, in the order the nav renders.
WORKSPACE_TABS = ('process', 'cleaned', 'cowork', 'analyse', 'nuban', 'intel')

DEFAULT_TAB = 'process'


def _shell(request: Request, tab: str = DEFAULT_TAB, **extra) -> HTMLResponse:
    """Render the workspace shell with its nav already pointed at `tab`."""
    versions = {
        'auth_core_js': _asset_version('static/js/auth-core.js'),
        'app_js': _asset_version('static/js/app.js'),
        'session_js': _asset_version('static/js/session.js'),
        'style_css': _asset_version('static/css/style.css'),
    }
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={'active_tab': tab, 'asset_versions': versions, **extra},
    )


@router.get('/app', response_class=HTMLResponse)
def workspace_root(request: Request):
    """Canonicalise the bare shell onto its default tab."""
    return RedirectResponse(f'/app/{DEFAULT_TAB}', status_code=307)


@router.get('/app/cowork/{space_id}', response_class=HTMLResponse)
def workspace_space(request: Request, space_id: str):
    """Deep link into a single coworking space; the guarded JS resolves the id."""
    return _shell(request, 'cowork', space_id=space_id)


@router.get('/app/{tab}', response_class=HTMLResponse)
def workspace_tab(request: Request, tab: str):
    """Every tab is its own URL so a refresh or a shared link lands on it."""
    if tab not in WORKSPACE_TABS:
        return RedirectResponse(f'/app/{DEFAULT_TAB}', status_code=307)
    return _shell(request, tab)


@router.get('/cowork/join/{token}', response_class=HTMLResponse)
def workspace_invite(request: Request, token: str):
    """Invite landing shell; the join itself is redeemed by the guarded JS."""
    return _shell(request, 'cowork', invite_token=token)
