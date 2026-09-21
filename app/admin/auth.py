from starlette.requests import Request
from starlette_admin.auth import AdminUser, AuthProvider, LoginFailed

from app.core.database import SessionLocal
from app.core.models import User
from app.core.security import verify_password


class AdminAuthProvider(AuthProvider):
    """Session-based auth for Starlette Admin, restricted to active superusers."""

    async def login(
        self, username: str, password: str, remember_me: bool, request: Request
    ):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == username).first()
            if (
                user is None
                or not user.is_active
                or not user.is_superuser
                or not verify_password(password, user.hashed_password)
            ):
                raise LoginFailed("Invalid email or password")
            request.session["admin_user_id"] = user.id
        finally:
            db.close()

    async def authenticate(self, request: Request) -> AdminUser | None:
        user_id = request.session.get("admin_user_id")
        if not user_id:
            return None

        db = SessionLocal()
        try:
            user = db.get(User, user_id)
            if user is not None and user.is_active and user.is_superuser:
                return AdminUser(username=user.email)
        finally:
            db.close()
        return None

    async def logout(self, request: Request):
        request.session.clear()
