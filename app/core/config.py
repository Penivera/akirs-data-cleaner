from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pydantic import Field

class Settings(BaseSettings):
    paystack_secret_key: Optional[str] = Field(
        default=None, 
        validation_alias="PAYSTACK_SECRET_KEY",
        description="Paystack Secret Key for NUBAN resolution"
    )
    
    flutterwave_secret_key: Optional[str] = Field(
        default=None,
        validation_alias="FLUTTERWAVE_SECRET_KEY",
        description="Flutterwave Secret Key for fallback NUBAN resolution"
    )
    
    intelligence_token: Optional[str] = Field(
        default=None,
        validation_alias="INTELLIGENCE_TOKEN",
        description="Authorization Bearer Token for live DB Verification"
    )
    
    app_name: str = Field(
        default="AKIRS Batch File Cleaner",
        description="Name of the application"
    )
    
    debug: bool = Field(
        default=False,
        description="Debug mode"
    )

    secret_key: str = Field(
        default="change-me-in-production",
        validation_alias="SECRET_KEY",
        description="Secret key used to sign JWT access/refresh tokens and admin sessions"
    )

    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias="DATABASE_URL",
        description="SQLAlchemy database URL (SQLite by default, PostgreSQL supported)"
    )

    admin_email: str = Field(
        default="admin@akirs.local",
        validation_alias="ADMIN_EMAIL",
        description="Email of the superuser seeded on first startup"
    )

    admin_password: Optional[str] = Field(
        default=None,
        validation_alias="ADMIN_PASSWORD",
        description="Password for the seeded superuser. If unset, a random one is generated and logged once."
    )

    access_token_expire_minutes: int = Field(
        default=30,
        validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES",
        description="JWT access token lifetime in minutes"
    )

    refresh_token_expire_days: int = Field(
        default=7,
        validation_alias="REFRESH_TOKEN_EXPIRE_DAYS",
        description="JWT refresh token lifetime in days"
    )

    admin_session_max_age: int = Field(
        default=14 * 24 * 3600,
        validation_alias="ADMIN_SESSION_MAX_AGE",
        description="Starlette Admin session cookie lifetime in seconds"
    )

    admin_session_https_only: bool = Field(
        default=False,
        validation_alias="ADMIN_SESSION_HTTPS_ONLY",
        description="Mark the Starlette Admin session cookie as HTTPS-only"
    )

    totp_issuer: str = Field(
        default="AKIRS Data Toolkit",
        validation_alias="TOTP_ISSUER",
        description="Issuer name shown in authenticator apps for TOTP 2FA"
    )

    mfa_challenge_expire_minutes: int = Field(
        default=10,
        validation_alias="MFA_CHALLENGE_EXPIRE_MINUTES",
        description="Lifetime of the short-lived MFA challenge token in minutes"
    )

    recovery_code_count: int = Field(
        default=10,
        validation_alias="RECOVERY_CODE_COUNT",
        description="Number of one-time recovery codes generated when 2FA is enabled"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
