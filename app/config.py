"""Environment-backed settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


def normalize_database_url(url: str) -> str:
    """Accept SQLite and Postgres URLs, including Render's postgres:// form.

    The app always talks to SQLAlchemy through an async driver. Callers can set
    DATABASE_URL to sqlite:///..., postgres://..., or postgresql://... and no
    application code has to change when moving off SQLite.
    """

    cleaned = url.strip()
    if cleaned.startswith("postgres://"):
        cleaned = "postgresql+asyncpg://" + cleaned[len("postgres://") :]
    elif cleaned.startswith("postgresql://"):
        cleaned = "postgresql+asyncpg://" + cleaned[len("postgresql://") :]
    elif cleaned.startswith("sqlite://") and not cleaned.startswith("sqlite+aiosqlite://"):
        cleaned = "sqlite+aiosqlite://" + cleaned[len("sqlite://") :]
    if cleaned.startswith("postgresql+asyncpg://") and "sslmode=" in cleaned:
        cleaned = cleaned.replace("sslmode=", "ssl=")
    return cleaned


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./taskflow.db"
    secret_key: str = "dev-only-change-me"
    cookie_secure: bool = False
    upload_dir: str = "uploads"
    max_upload_bytes: int = 5 * 1024 * 1024
    app_base_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False

    @property
    def database_url_normalized(self) -> str:
        return normalize_database_url(self.database_url)

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = ROOT / path
        return path

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host.strip() and self.smtp_from.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
