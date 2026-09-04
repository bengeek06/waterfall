from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Locate a repo-root .env by walking up from this file.

    Absent in containers, where environment variables are injected directly.
    """
    current = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


_ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="waterfall", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    database_url: str = Field(
        default="sqlite+pysqlite:///./waterfall.db",
        alias="DATABASE_URL",
    )
    secret_key: str = Field(default="", alias="SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_minutes: int = Field(default=1440, alias="REFRESH_TOKEN_EXPIRE_MINUTES")
    auth_allow_public_register: bool | None = Field(
        default=None, alias="AUTH_ALLOW_PUBLIC_REGISTER"
    )
    auth_rate_limit_attempts: int = Field(default=10, alias="AUTH_RATE_LIMIT_ATTEMPTS")
    auth_rate_limit_window_seconds: int = Field(default=60, alias="AUTH_RATE_LIMIT_WINDOW_SECONDS")
    auth_max_failed_attempts: int = Field(default=5, alias="AUTH_MAX_FAILED_ATTEMPTS")
    auth_lockout_minutes: int = Field(default=15, alias="AUTH_LOCKOUT_MINUTES")
    cors_allow_origins: str | None = Field(default=None, alias="CORS_ALLOW_ORIGINS")
    import_storage_path: str = Field(default=".waterfall-imports", alias="IMPORT_STORAGE_PATH")
    import_max_upload_bytes: int = Field(
        default=25 * 1024 * 1024,
        alias="IMPORT_MAX_UPLOAD_BYTES",
        ge=1,
    )

    def is_public_registration_enabled(self) -> bool:
        if self.auth_allow_public_register is not None:
            return self.auth_allow_public_register
        return self.app_env in {"dev", "test"}

    def get_cors_allow_origins(self) -> list[str]:
        if self.cors_allow_origins:
            return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]

        if self.app_env in {"dev", "test"}:
            return ["http://localhost:3000", "http://127.0.0.1:3000"]

        return []


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    secret_key = settings.secret_key.strip()
    if not secret_key or secret_key == "change-me":
        raise ValueError("SECRET_KEY must be set")
    return settings
