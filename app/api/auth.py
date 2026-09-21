import secrets
from datetime import datetime, timezone
from typing import List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.mfa import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    provisioning_uri,
    qr_svg_data_uri,
    verify_totp,
)
from app.core.models import RecoveryCode, RefreshToken, User
from app.core.security import (
    MFA_CHALLENGE_TYPE,
    MFA_SETUP_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_mfa_challenge_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.services.audit import log_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

MIN_PASSWORD_LENGTH = 8


class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not value or "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("A valid email address is required")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if len(value) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not value or "@" not in value:
            raise ValueError("A valid email address is required")
        return value


class MfaChallengeResponse(BaseModel):
    mfa_required: bool
    setup_required: bool
    challenge_token: str


class MfaSetupRequest(BaseModel):
    challenge_token: str


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_url: str
    qr_svg: str


class MfaEnableRequest(BaseModel):
    challenge_token: str
    code: str


class MfaVerifyRequest(BaseModel):
    challenge_token: str
    code: Optional[str] = None
    recovery_code: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None
    all_devices: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_approved: bool
    is_superuser: bool
    totp_enabled: bool
    created_at: datetime
    last_login: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class MfaTokenResponse(TokenResponse):
    recovery_codes: Optional[List[str]] = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _issue_tokens(db: Session, user: User) -> TokenResponse:
    access_token = create_access_token(user.id, user.token_version)
    refresh_token = create_refresh_token(user.id, user.token_version)

    payload = decode_token(refresh_token)
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=payload["jti"],
            token_hash=hash_token(refresh_token),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    )
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


def _load_challenge(db: Session, token: str, expected_type: str) -> User:
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token"
        )

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token"
        )

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token"
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active or not user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token"
        )
    if payload.get("ver") != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge token"
        )
    return user


def _consume_recovery_code(db: Session, user: User, code: str) -> bool:
    candidate = hash_recovery_code(code)
    for record in user.recovery_codes:
        if not record.used and secrets.compare_digest(record.code_hash, candidate):
            record.used = True
            db.commit()
            return True
    return False


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)):
    existing = db.query(User).filter(func.lower(User.email) == payload.email).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=payload.email,
        full_name=(payload.full_name or "").strip() or None,
        hashed_password=hash_password(payload.password),
        is_active=True,
        is_approved=False,
        is_superuser=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_audit("signup", user=user, status="pending", request=request)
    return {
        "detail": "Account created. An administrator must approve it before you can sign in.",
        "user_id": user.id,
    }


@router.post("/login", response_model=MfaChallengeResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email).first()

    if user is None or not verify_password(payload.password, user.hashed_password):
        log_audit(
            "login",
            status="failed",
            detail=f"Invalid credentials for {payload.email}",
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        log_audit(
            "login", user=user, status="failed", detail="Inactive account", request=request
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    if not user.is_approved:
        log_audit(
            "login",
            user=user,
            status="failed",
            detail="Account pending approval",
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending administrator approval",
        )

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    setup_required = not user.totp_enabled
    challenge_token = create_mfa_challenge_token(
        user.id, setup_required, user.token_version
    )
    log_audit("login", user=user, status="mfa_challenge", request=request)
    return MfaChallengeResponse(
        mfa_required=not setup_required,
        setup_required=setup_required,
        challenge_token=challenge_token,
    )


@router.post("/2fa/setup", response_model=MfaSetupResponse)
def setup_2fa(
    payload: MfaSetupRequest, request: Request, db: Session = Depends(get_db)
):
    user = _load_challenge(db, payload.challenge_token, MFA_SETUP_TYPE)

    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is already enabled",
        )

    secret = generate_totp_secret()
    user.pending_totp_secret = secret
    db.commit()

    otpauth_url = provisioning_uri(secret, user.email)
    log_audit("2fa_setup_started", user=user, request=request)
    return MfaSetupResponse(
        secret=secret,
        otpauth_url=otpauth_url,
        qr_svg=qr_svg_data_uri(otpauth_url),
    )


@router.post("/2fa/enable", response_model=MfaTokenResponse)
def enable_2fa(payload: MfaEnableRequest, request: Request, db: Session = Depends(get_db)):
    user = _load_challenge(db, payload.challenge_token, MFA_SETUP_TYPE)

    if not user.pending_totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start two-factor setup before enabling it",
        )

    if not verify_totp(user.pending_totp_secret, payload.code):
        log_audit(
            "2fa_enable", user=user, status="failed", detail="Invalid code", request=request
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code"
        )

    user.totp_secret = user.pending_totp_secret
    user.pending_totp_secret = None
    user.totp_enabled = True

    db.query(RecoveryCode).filter(RecoveryCode.user_id == user.id).delete()
    recovery_codes = generate_recovery_codes()
    for code in recovery_codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(code)))
    db.commit()
    db.refresh(user)

    tokens = _issue_tokens(db, user)
    log_audit("2fa_enabled", user=user, status="success", request=request)
    return MfaTokenResponse(**tokens.model_dump(), recovery_codes=recovery_codes)


@router.post("/2fa/verify", response_model=MfaTokenResponse)
def verify_2fa(payload: MfaVerifyRequest, request: Request, db: Session = Depends(get_db)):
    user = _load_challenge(db, payload.challenge_token, MFA_CHALLENGE_TYPE)

    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not configured",
        )

    verified = False
    used_recovery = False
    if payload.code and verify_totp(user.totp_secret, payload.code):
        verified = True
    elif payload.recovery_code and _consume_recovery_code(
        db, user, payload.recovery_code
    ):
        verified = True
        used_recovery = True

    if not verified:
        log_audit(
            "2fa_verify", user=user, status="failed", detail="Invalid code", request=request
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code"
        )

    tokens = _issue_tokens(db, user)
    log_audit(
        "login",
        user=user,
        status="success",
        detail="recovery_code" if used_recovery else "totp",
        request=request,
    )
    return MfaTokenResponse(**tokens.model_dump())


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    try:
        token_payload = decode_token(payload.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    if token_payload.get("type") != REFRESH_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.jti == token_payload.get("jti"))
        .first()
    )
    if record is None or record.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
        )

    if _as_utc(record.expires_at) <= datetime.now(timezone.utc):
        record.revoked = True
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired"
        )

    if record.token_hash != hash_token(payload.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user = db.get(User, record.user_id)
    if user is None or not user.is_active or not user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is disabled"
        )

    if token_payload.get("ver") != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
        )

    record.revoked = True
    db.commit()

    tokens = _issue_tokens(db, user)
    log_audit("token_refresh", user=user, status="success", request=request)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: LogoutRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.all_devices:
        db.query(RefreshToken).filter(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked.is_(False),
        ).update({RefreshToken.revoked: True})
        current_user.token_version += 1
        db.commit()
    elif payload.refresh_token:
        record = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == current_user.id,
                RefreshToken.token_hash == hash_token(payload.refresh_token),
            )
            .first()
        )
        if record is not None:
            record.revoked = True
            db.commit()

    log_audit("logout", user=current_user, status="success", request=request)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
