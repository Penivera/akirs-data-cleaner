from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pydantic import Field, model_validator

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

    app_env: str = Field(
        default="development",
        validation_alias="APP_ENV",
        description="Deployment environment: development or production",
    )

    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias="DATABASE_URL",
        description="SQLAlchemy database URL. Production requires PostgreSQL.",
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

    # --- File handling -------------------------------------------------

    max_upload_size_mb: int = Field(
        default=50,
        validation_alias="MAX_UPLOAD_SIZE_MB",
        description="Maximum upload file size in megabytes"
    )

    allowed_extensions: str = Field(
        default=".xlsx,.xls,.csv",
        validation_alias="ALLOWED_EXTENSIONS",
        description="Comma-separated list of allowed file extensions"
    )

    # --- Cleanup job ---------------------------------------------------

    cleanup_enabled: bool = Field(
        default=True,
        validation_alias="CLEANUP_ENABLED",
        description="Enable the daily file cleanup background job"
    )

    cleanup_max_age_hours: int = Field(
        default=24,
        validation_alias="CLEANUP_MAX_AGE_HOURS",
        description="Files older than this many hours will be deleted by the cleanup job"
    )

    cleanup_interval_hours: int = Field(
        default=24,
        validation_alias="CLEANUP_INTERVAL_HOURS",
        description="How often the cleanup job runs, in hours"
    )

    # --- Performance ---------------------------------------------------

    processing_threads: int = Field(
        default=2,
        validation_alias="PROCESSING_THREADS",
        description=(
            "Size of the dedicated thread pool used for CPU-bound file processing. "
            "Keep this small: each concurrent job can load a whole workbook into memory."
        )
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _validate_database(self) -> "Settings":
        if self.app_env.lower() == "production" and not self.database_url.startswith(
            ("postgresql://", "postgres://", "postgresql+asyncpg://")
        ):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL in production "
                f"(APP_ENV={self.app_env!r}); SQLite is not supported in production."
            )
        return self


settings = Settings()
