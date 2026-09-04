from __future__ import annotations

import os

from pydantic import EmailStr, TypeAdapter, ValidationError

from waterfall.core.security import hash_password, normalize_email, validate_password
from waterfall.db.session import get_session_factory
from waterfall.models.user import User

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def main() -> None:
    email = normalize_email(os.getenv("WF_ADMIN_EMAIL", "admin@example.com"))
    password = os.getenv("WF_ADMIN_PASSWORD")
    if password is None:
        raise ValueError("WF_ADMIN_PASSWORD must be set to seed the admin user")
    is_active = _as_bool(os.getenv("WF_ADMIN_IS_ACTIVE"), default=True)

    try:
        validated_email = _EMAIL_ADAPTER.validate_python(email)
    except ValidationError as exc:
        raise ValueError(f"WF_ADMIN_EMAIL is invalid: {email}") from exc

    if not isinstance(validated_email, str):
        raise ValueError(f"WF_ADMIN_EMAIL is invalid: {email}")
    email = validated_email

    validate_password(password)

    session_factory = get_session_factory()
    with session_factory() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(
                email=email,
                hashed_password=hash_password(password),
                is_active=is_active,
                is_admin=True,
            )
            db.add(user)
            db.commit()
            print(f"Created admin user: {email}")
            return

        user.hashed_password = hash_password(password)
        user.is_active = is_active
        user.is_admin = True
        # Reseeding must also clear any prior lockout so the account is usable again.
        user.failed_login_attempts = 0
        user.locked_until = None
        db.add(user)
        db.commit()
        print(f"Updated admin user: {email}")


if __name__ == "__main__":
    main()
