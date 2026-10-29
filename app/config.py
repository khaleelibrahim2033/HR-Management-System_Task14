from datetime import time

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./worksphere.db"
    jwt_secret_key: str = Field(default="development-only-insecure-secret-key-change-before-deployment", min_length=32)
    jwt_access_token_minutes: int = 60
    attendance_late_after: time = time(9)
    frontend_origins: str = "http://localhost:5173"
    bootstrap_admin_username: str | None = None
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    document_storage_dir: str = "uploads"
    document_max_size_bytes: int = Field(default=10_485_760, ge=1, le=52_428_800)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
