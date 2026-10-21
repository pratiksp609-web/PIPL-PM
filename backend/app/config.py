"""Application configuration, loaded from environment variables (see .env.example)."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PIPL AI Project Management System"
    app_env: str = "development"  # development | test | production
    secret_key: str = "change-me-in-env"
    database_url: str = "postgresql+psycopg://pipl:pipl@localhost:5432/pipl"

    # Sessions / cookies
    session_hours: int = 12
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173"

    # File storage
    upload_dir: str = str(BASE_DIR / "storage" / "uploads")
    max_upload_mb: int = 25

    # AI provider (optional). Never exposed to the frontend.
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_timeout_seconds: int = 120

    # Email (optional). Email notifications are only attempted when SMTP_HOST is set.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    # Scheduler
    scheduler_enabled: bool = True
    scheduler_interval_minutes: int = 5
    default_timezone: str = "Asia/Kolkata"

    # Rate limiting
    login_rate_limit_per_minute: int = 10
    api_rate_limit_per_minute: int = 600

    first_admin_email: str | None = None
    first_admin_password: str | None = None

    log_level: str = "INFO"
    # Seed data is never allowed when app_env == production
    allow_sample_data: bool = Field(default=True)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
