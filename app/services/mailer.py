"""SMTP mail delivery for coworking job notifications.

Email is disabled unless SMTP_HOST is configured; send_mail then becomes a
no-op so the platform works without a mail server.
"""
import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("app.mailer")


def mail_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_mail(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success, False otherwise.

    Synchronous on purpose: called from the Celery worker (or the CPU thread
    pool), never from the event loop.
    """
    if not mail_enabled():
        logger.info("Email skipped (SMTP not configured): %s - %s", to, subject)
        return False

    try:
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(message)
        logger.info("Sent email to %s: %s", to, subject)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to send email to %s (%s): %r", to, subject, exc)
        return False


def notify_job_done(
    to: str,
    user_name: str,
    space_name: str,
    file_count: int,
    base_url: str,
    space_id: str,
) -> bool:
    """Send the 'bulk coworking job finished' notification email."""
    subject = f"[AKIRS] Your coworking batch finished ({file_count} files)"
    body = (
        f"Hi {user_name},\n\n"
        f"The bulk processing job in coworking space \"{space_name}\" has "
        f"finished ({file_count} file(s)).\n\n"
        f"Open the space to view results: "
        f"{base_url.rstrip('/')}/api/cowork/spaces/{space_id}\n\n"
        "AKIRS Data Toolkit"
    )
    return send_mail(to, subject, body)
