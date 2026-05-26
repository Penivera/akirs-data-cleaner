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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
