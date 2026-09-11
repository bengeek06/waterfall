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
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    # Kept out of REDIS_URL on purpose: a password embedded in the URL must be
    # percent-encoded, and `openssl rand -base64 24` routinely emits `/`, `+` and `@`,
    # which silently corrupt the parsed host/password (redis-py would connect to the
    # wrong host and every login would fail closed with a 503, with no usable
    # diagnostic). Passing it as its own setting removes the encoding hazard entirely.
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")
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
    # Uploaded MS Project sources live in an S3-compatible object store (Garage), not on
    # a container-local disk: a bind/volume mount ties the API to a single machine and is
    # lost whenever the container is recreated. The endpoint is a plain URL and the bucket
    # a plain name; only the two credentials below are secrets, and they are deliberately
    # separate settings rather than embedded in the endpoint URL (same rationale as
    # redis_password above -- a generated secret key routinely contains URL separators).
    garage_endpoint_url: str = Field(default="http://localhost:3900", alias="GARAGE_ENDPOINT_URL")
    garage_access_key_id: str = Field(default="", alias="GARAGE_ACCESS_KEY_ID")
    garage_secret_access_key: str = Field(default="", alias="GARAGE_SECRET_ACCESS_KEY")
    garage_bucket: str = Field(default="waterfall-imports", alias="GARAGE_BUCKET")
    # SigV4 signs the region into the credential scope, so it must match the `s3_region`
    # of infra/docker/garage/garage.toml (or of whatever S3-compatible store is used
    # instead -- a mismatch surfaces as an opaque SignatureDoesNotMatch, hence the
    # commented line in .env.example). Only needs overriding in that latter case.
    garage_region: str = Field(default="garage", alias="GARAGE_REGION")
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


def _validate_settings(settings: Settings) -> Settings:
    secret_key = settings.secret_key.strip()
    if not secret_key or secret_key == "change-me":
        raise ValueError("SECRET_KEY must be set")
    # Same fail-at-boot treatment: the compose file guards these with `${...:?}`, but a
    # native dev run (Configuration A) has nothing to catch them. Empty credentials still
    # produce a perfectly well-formed SigV4 signature, so the only symptom would be an
    # opaque 503 on the first import, possibly hours after the misconfiguration.
    if not settings.garage_access_key_id or not settings.garage_secret_access_key:
        raise ValueError("GARAGE_ACCESS_KEY_ID and GARAGE_SECRET_ACCESS_KEY must be set")
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _validate_settings(Settings())
