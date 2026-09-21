import logging
from typing import Optional

from starlette.requests import Request

from app.core.database import SessionLocal
from app.core.models import AuditLog, User

logger = logging.getLogger("app.audit")


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    if request.client is not None:
        return request.client.host
    return None


def log_audit(
    action: str,
    user: Optional[User] = None,
    filename: Optional[str] = None,
    status: Optional[str] = None,
    detail: Optional[str] = None,
    request: Optional[Request] = None,
) -> None:
    """Persist an audit entry. Never raises so it cannot break a request flow."""
    try:
        db = SessionLocal()
        try:
            entry = AuditLog(
                user_id=user.id if user is not None else None,
                user_email=user.email if user is not None else None,
                action=action,
                filename=filename,
                status=status,
                detail=detail,
                ip=_client_ip(request),
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to write audit log (%s): %r", action, exc)
