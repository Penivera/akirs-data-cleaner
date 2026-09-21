"""Public account pages, separate from the protected workspace routers."""
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
    return templates.TemplateResponse(request=request, name='auth.html')
