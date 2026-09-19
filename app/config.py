"""All settings come from environment variables (12-factor style).

For local development they are read from the .env file in the project folder.
.env.example lists every name; it never contains real secrets.
"""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_FOLDER / ".env")


def _get(name, default=""):
    # An empty value (e.g. "STORAGE_DIR=" copied from .env.example) means "use the default".
    return os.getenv(name) or default


def _int(name, default):
    return int(_get(name, str(default)))


def _list(name, default=""):
    return [item.strip() for item in _get(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    environment: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    # Used to sign short-lived document upload/download links. Must be long and random.
    secret_key: str
    access_token_minutes: int
    refresh_token_days: int
    password_reset_minutes: int
    login_rate_limit_per_minute: int
    app_rate_limit_per_minute: int
    cors_origins: list
    storage_dir: Path
    max_upload_bytes: int
    signed_url_seconds: int
    notification_max_attempts: int

    @property
    def is_production(self):
        return self.environment == "production"


@lru_cache
def get_settings():
    # Stop with a clear message if a required setting is missing.
    for name in ["DB_NAME", "DB_USER", "DB_PASSWORD", "SECRET_KEY"]:
        if not os.getenv(name):
            raise ValueError(f"Set {name} in your .env file (see .env.example).")

    secret_key = os.environ["SECRET_KEY"]
    if len(secret_key) < 32:
        raise ValueError("SECRET_KEY must be at least 32 characters long.")

    return Settings(
        environment=_get("ENVIRONMENT", "development"),
        db_host=_get("DB_HOST", "127.0.0.1"),
        db_port=_int("DB_PORT", 5432),
        db_name=os.environ["DB_NAME"],
        db_user=os.environ["DB_USER"],
        db_password=os.environ["DB_PASSWORD"],
        secret_key=secret_key,
        access_token_minutes=_int("ACCESS_TOKEN_MINUTES", 15),
        refresh_token_days=_int("REFRESH_TOKEN_DAYS", 14),
        password_reset_minutes=_int("PASSWORD_RESET_MINUTES", 30),
        login_rate_limit_per_minute=_int("LOGIN_RATE_LIMIT_PER_MINUTE", 5),
        app_rate_limit_per_minute=_int("APP_RATE_LIMIT_PER_MINUTE", 120),
        cors_origins=_list("CORS_ORIGINS"),
        storage_dir=Path(_get("STORAGE_DIR", str(PROJECT_FOLDER / "storage"))),
        max_upload_bytes=_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
        signed_url_seconds=_int("SIGNED_URL_SECONDS", 300),
        notification_max_attempts=_int("NOTIFICATION_MAX_ATTEMPTS", 5),
    )
