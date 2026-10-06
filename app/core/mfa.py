import pyotp
import segno

from app.core.config import settings


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=account_name, issuer_name=settings.totp_issuer
    )


def qr_svg_data_uri(otpauth_url: str) -> str:
    """Render an otpauth:// URI as a scannable SVG QR code data URI."""
    return segno.make(otpauth_url, error="m").svg_data_uri(scale=6, border=2)


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    if not secret or not code:
        return False
    code = str(code).strip().replace(" ", "")
    if not code.isdigit():
        return False
    try:
        return pyotp.totp.TOTP(secret).verify(code, valid_window=valid_window)
    except Exception:
        return False

