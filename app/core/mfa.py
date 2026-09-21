import hashlib
import secrets
from typing import List

import pyotp

from app.core.config import settings


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=account_name, issuer_name=settings.totp_issuer
    )


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


def generate_recovery_codes(count: int | None = None) -> List[str]:
    count = count or settings.recovery_code_count
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:10]}")
    return codes


def normalize_recovery_code(code: str) -> str:
    return str(code).strip().lower().replace(" ", "")


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()
