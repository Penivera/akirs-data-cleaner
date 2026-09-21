import logging
import secrets

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from urllib.parse import urlsplit
from starlette.middleware.sessions import SessionMiddleware

from app.admin.setup import setup_admin
from app.api.auth import router as auth_router
from app.api.pages import router as pages_router
from app.api.routes import router as main_router
from app.api.analytics import router as analytics_router
from app.api.nuban import router as nuban_router
from app.api.intelligence import router as intelligence_router
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.deps import get_current_user
from app.core.models import User
from app.core.security import hash_password

logger = logging.getLogger("app.startup")
logging.basicConfig(level=logging.INFO)


def seed_superuser() -> None:
    """Create the initial superuser account when the users table is empty."""
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return

        password = settings.admin_password or secrets.token_urlsafe(12)
        user = User(
            email=settings.admin_email.strip().lower(),
            full_name="Administrator",
            hashed_password=hash_password(password),
            is_active=True,
            is_approved=True,
            is_superuser=True,
        )
        db.add(user)
        db.commit()

        if settings.admin_password:
            logger.info("Seeded superuser %s", user.email)
        else:
            logger.warning(
                "Seeded superuser %s with generated password: %s "
                "(set ADMIN_PASSWORD to control this)",
                user.email,
                password,
            )
    finally:
        db.close()


init_db()
seed_superuser()

if settings.secret_key == "change-me-in-production" or len(settings.secret_key) < 32:
    logger.warning(
        "SECRET_KEY is missing, default, or shorter than 32 bytes. "
        "Set a long random SECRET_KEY before deploying to production."
    )

app = FastAPI(title="AKIRS Batch File Cleaner")


@app.middleware("http")
async def browser_auth(request, call_next):
    # Reject cross-origin writes. Auth is Bearer-only (no auth cookie); the
    # middleware only shapes browser navigation and HTMX 401 responses.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if (origin and urlsplit(origin).netloc != request.url.netloc) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
    response = await call_next(request)
    if response.status_code == 401 and request.url.path == "/" and "text/html" in request.headers.get("accept", ""):
        response = RedirectResponse("/auth", status_code=303)
    elif response.status_code == 401 and request.headers.get("hx-request") == "true":
        response.headers["HX-Redirect"] = "/auth"
    if request.url.path == "/" or request.url.path.startswith(("/auth", "/api/auth")):
        response.headers["Cache-Control"] = "no-store"
    return response

# Starlette Admin uses a session cookie scoped to the admin UI only. The rest of
# the application authenticates statelessly via JWT Bearer tokens.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="akirs_admin_session",
    max_age=settings.admin_session_max_age,
    same_site="lax",
    https_only=settings.admin_session_https_only,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Public authentication endpoints
app.include_router(auth_router)
app.include_router(pages_router)

# Protected application routers
protected = [Depends(get_current_user)]
app.include_router(main_router, dependencies=protected)
app.include_router(analytics_router, dependencies=protected)
app.include_router(nuban_router, dependencies=protected)
app.include_router(intelligence_router, dependencies=protected)

# Starlette Admin (own session-based auth, superusers only)
setup_admin(app)
