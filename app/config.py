"""Environment-backed settings."""

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
INSECURE_SECRET = "dev-only-change-me"
logger = logging.getLogger("taskflow")


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
    secret_key: str = INSECURE_SECRET
    cookie_secure: bool = False
    taskflow_env: str = "development"
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


def enforce_runtime_safety(
    *,
    secret_key: str | None = None,
    cookie_secure: bool | None = None,
    taskflow_env: str | None = None,
    render: str | None = None,
) -> None:
    """Stop production when the signing key or the cookie flag is still a dev default.

    Local development keeps the insecure defaults so HTTP on localhost still runs.
    Production is TASKFLOW_ENV=production (or prod), or Render's RENDER=true.
    """

    current = get_settings()
    secret = current.secret_key if secret_key is None else secret_key
    secure = current.cookie_secure if cookie_secure is None else cookie_secure
    env_name = current.taskflow_env if taskflow_env is None else taskflow_env
    render_flag = os.environ.get("RENDER", "") if render is None else render
    secret_text = (secret or "").strip()
    insecure = not secret_text or secret_text == INSECURE_SECRET
    production = env_name.strip().lower() in {"production", "prod"} or render_flag.strip().lower() == "true"
    if production and insecure:
        raise SystemExit(
            "Refusing to start: SECRET_KEY is missing or is the development default."
        )
    if production and not secure:
        raise SystemExit(
            "Refusing to start: COOKIE_SECURE must be true when TaskFlow runs in production."
        )
    if insecure:
        logger.warning(
            "SECRET_KEY is the development default. TaskFlow refuses to start when TASKFLOW_ENV=production."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
