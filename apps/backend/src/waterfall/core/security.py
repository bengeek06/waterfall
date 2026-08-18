from datetime import UTC, datetime, timedelta
from typing import Literal

from jose import JWTError, jwt
from pwdlib import PasswordHash

from waterfall.core.config import get_settings

password_hash = PasswordHash.recommended()
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256


def validate_password(password: str) -> str:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            "Password must be between "
            f"{MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters long"
        )
    return password


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _create_token(
    subject: str,
    token_type: Literal["access", "refresh"],
    expire_minutes: int,
    token_version: int,
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": normalize_email(subject),
        "typ": token_type,
        "tv": token_version,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, token_version: int) -> str:
    settings = get_settings()
    return _create_token(
        subject=subject,
        token_type="access",
        expire_minutes=settings.access_token_expire_minutes,
        token_version=token_version,
    )


def create_refresh_token(subject: str, token_version: int) -> str:
    settings = get_settings()
    return _create_token(
        subject=subject,
        token_type="refresh",
        expire_minutes=settings.refresh_token_expire_minutes,
        token_version=token_version,
    )


def _decode_token(
    token: str,
    expected_type: Literal["access", "refresh"],
) -> tuple[str, int] | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None

    token_type = payload.get("typ")
    if token_type != expected_type:
        return None

    subject = payload.get("sub")
    token_version = payload.get("tv")
    if not isinstance(subject, str) or not isinstance(token_version, int):
        return None
    return normalize_email(subject), token_version


def decode_access_token(token: str) -> tuple[str, int] | None:
    return _decode_token(token, expected_type="access")


def decode_refresh_token(token: str) -> tuple[str, int] | None:
    return _decode_token(token, expected_type="refresh")
