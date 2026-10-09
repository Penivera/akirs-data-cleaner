import logging
import secrets
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from urllib.parse import urlsplit
from starlette.middleware.sessions import SessionMiddleware

from app.admin.setup import setup_admin
from app.api.auth import router as auth_router
from app.api.pages import router as pages_router
from app.api.routes import router as main_router
from app.api.analytics import router as analytics_router
from app.api.nuban import router as nuban_router
from app.api.intelligence import router as intelligence_router
from app.api.cowork import router as cowork_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.deps import get_current_user
from app.core.executor import shutdown_executor
from app.core.models import User
from app.core.security import hash_password, verify_password
from app.services.cleanup import cleanup_stale_files

logger = logging.getLogger("app.startup")
logging.basicConfig(level=logging.INFO)


async def seed_superuser() -> None:
    """Create the superuser on first run, and keep it in sync with ADMIN_* config."""
    async with AsyncSessionLocal() as db:
        email = settings.admin_email.strip().lower()
        result = await db.execute(select(User).where(func.lower(User.email) == email))
        user = result.scalars().first()

        if user is None:
            password = settings.admin_password or secrets.token_urlsafe(12)
            user = User(
                email=email,
                full_name="Administrator",
                hashed_password=hash_password(password),
                is_active=True,
                is_approved=True,
                is_superuser=True,
            )
            db.add(user)
            try:
                await db.commit()
            except IntegrityError:
                # Another worker seeded the superuser concurrently.
                await db.rollback()
                return

            if settings.admin_password:
                logger.info("Seeded superuser %s", user.email)
            else:
                logger.warning(
                    "Seeded superuser %s with generated password: %s "
                    "(set ADMIN_PASSWORD to control this)",
                    user.email,
                    password,
                )
            return

        # The account already exists. Reconcile it with the current configuration
        # so that setting or rotating ADMIN_PASSWORD takes effect on restart.
        changed = False
        if not user.is_superuser:
            user.is_superuser = True
            changed = True
        if not user.is_approved:
            user.is_approved = True
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if settings.admin_password and not verify_password(
            settings.admin_password, user.hashed_password
        ):
            user.hashed_password = hash_password(settings.admin_password)
            changed = True

        if changed:
            await db.commit()
            logger.info("Reconciled superuser %s from ADMIN_* configuration", user.email)


if settings.secret_key == "change-me-in-production" or len(settings.secret_key) < 32:
    logger.warning(
        "SECRET_KEY is missing, default, or shorter than 32 bytes. "
        "Set a long random SECRET_KEY before deploying to production."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables and seed the superuser before serving requests.
    await init_db()
    await seed_superuser()

    # Startup: start the cleanup scheduler
    if settings.cleanup_enabled:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            cleanup_stale_files,
            trigger=IntervalTrigger(hours=settings.cleanup_interval_hours),
            id="daily_cleanup",
            name="Delete stale uploads and cleaned files",
            replace_existing=True,
        )
        scheduler.start()
        logger.info(
            "Started cleanup scheduler (interval=%dh, max_age=%dh)",
            settings.cleanup_interval_hours,
            settings.cleanup_max_age_hours,
        )
        # Run once at startup to catch anything stale
        await cleanup_stale_files()
    else:
        logger.info("Cleanup job is disabled.")
    yield
    # Shutdown: stop the scheduler and the CPU thread pool
    if settings.cleanup_enabled:
        scheduler.shutdown(wait=False)
    shutdown_executor()


app = FastAPI(title="AKIRS Batch File Cleaner", lifespan=lifespan)


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
    if request.url.path == "/" or request.url.path.startswith(("/auth", "/api/auth", "/app", "/cowork/join")):
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
app.include_router(cowork_router, dependencies=protected)

# Starlette Admin (own session-based auth, superusers only)
setup_admin(app)
