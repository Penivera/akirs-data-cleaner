from starlette_admin.contrib.sqla import Admin

from app.admin.auth import AdminAuthProvider
from app.admin.views import AuditLogView, UserView
from app.core.config import settings
from app.core.database import engine
from app.core.models import AuditLog, User


def setup_admin(app) -> Admin:
    admin = Admin(
        engine,
        title="AKIRS Admin",
        base_url="/admin",
        auth_provider=AdminAuthProvider(),
        secret_key=settings.secret_key,
    )
    admin.add_view(UserView(User, icon="fa-solid fa-users"))
    admin.add_view(AuditLogView(AuditLog, icon="fa-solid fa-clipboard-list"))
    admin.mount_to(app)
    return admin
