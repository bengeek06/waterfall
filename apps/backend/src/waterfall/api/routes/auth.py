import logging
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user, get_current_admin_user
from waterfall.core.config import get_settings
from waterfall.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    normalize_email,
    verify_password,
)
from waterfall.db.session import get_db
from waterfall.models.user import User
from waterfall.schemas.auth import (
    PasswordChangeRequest,
    RefreshTokenRequest,
    Token,
    UserAdminRead,
    UserCreate,
    UserRead,
    UserRoleUpdate,
    UserStatusUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class LoginRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[datetime]] = defaultdict(deque)

    def allow(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        now = datetime.now(UTC)
        window_start = now - timedelta(seconds=window_seconds)
        attempts = self._attempts[key]
        while attempts and attempts[0] < window_start:
            attempts.popleft()
        if len(attempts) >= max_attempts:
            return False
        attempts.append(now)
        return True

    def clear(self) -> None:
        self._attempts.clear()


login_rate_limiter = LoginRateLimiter()


def _to_user_read(user: User) -> UserRead:
    return UserRead(id=user.id, email=user.email, is_active=user.is_active)


def _to_user_admin_read(user: User) -> UserAdminRead:
    return UserAdminRead(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
        failed_login_attempts=user.failed_login_attempts,
        locked_until=user.locked_until,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _issue_token_pair(user: User) -> Token:
    settings = get_settings()
    return Token(
        access_token=create_access_token(user.email, token_version=user.token_version),
        refreshToken=create_refresh_token(user.email, token_version=user.token_version),
        expiresIn=settings.access_token_expire_minutes * 60,
    )


def _get_user_by_email(db: Session, email: str) -> User | None:
    normalized_email = normalize_email(email)
    return db.query(User).filter(User.email == normalized_email).first()


def _to_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    settings = get_settings()
    if not settings.is_public_registration_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled"
        )

    normalized_email = normalize_email(payload.email)
    existing = _get_user_by_email(db, normalized_email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=normalized_email, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("auth.register.success", extra={"email": user.email})
    return _to_user_read(user)


@router.post("/token", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    settings = get_settings()
    client_ip = request.client.host if request.client is not None else "unknown"
    limiter_key = f"{client_ip}:{normalize_email(form_data.username)}"

    if not login_rate_limiter.allow(
        limiter_key,
        max_attempts=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    ):
        logger.warning(
            "auth.login.rate_limited", extra={"email": normalize_email(form_data.username)}
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )

    user = _get_user_by_email(db, form_data.username)
    now = datetime.now(UTC)

    locked_until = _to_utc_aware(user.locked_until) if user is not None else None
    if user is not None and locked_until is not None and locked_until > now:
        logger.warning("auth.login.locked", extra={"email": user.email})
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked",
        )

    if user is None or not verify_password(form_data.password, user.hashed_password):
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.auth_max_failed_attempts:
                user.failed_login_attempts = 0
                user.locked_until = now + timedelta(minutes=settings.auth_lockout_minutes)
            db.add(user)
            db.commit()
        logger.warning(
            "auth.login.invalid_credentials",
            extra={"email": normalize_email(form_data.username)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.warning("auth.login.inactive_user", extra={"email": user.email})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    user.failed_login_attempts = 0
    user.locked_until = None
    db.add(user)
    db.commit()

    logger.info("auth.login.success", extra={"email": user.email})
    return _issue_token_pair(user)


@router.post("/refresh", response_model=Token)
def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> Token:
    decoded = decode_refresh_token(payload.refresh_token)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email, token_version = decoded
    user = _get_user_by_email(db, email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    if user.token_version != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.token_version += 1
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("auth.refresh.success", extra={"email": user.email})
    return _issue_token_pair(user)


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_active_user)) -> UserRead:
    return _to_user_read(current_user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid current password"
        )

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.token_version += 1
    db.add(current_user)
    db.commit()
    logger.info("auth.password_changed", extra={"email": current_user.email})


@router.get("/users", response_model=list[UserAdminRead])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> list[UserAdminRead]:
    users = db.query(User).order_by(User.id.asc()).all()
    return [_to_user_admin_read(item) for item in users]


@router.patch("/users/{user_id}/status", response_model=UserAdminRead)
def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> UserAdminRead:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if current_admin.id == user.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate self"
        )

    user.is_active = payload.is_active
    if not payload.is_active:
        user.token_version += 1
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(
        "auth.user_status_updated", extra={"target_user_id": user.id, "is_active": user.is_active}
    )
    return _to_user_admin_read(user)


@router.patch("/users/{user_id}/role", response_model=UserAdminRead)
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> UserAdminRead:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if current_admin.id == user.id and not payload.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove own admin role"
        )

    user.is_admin = payload.is_admin
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(
        "auth.user_role_updated", extra={"target_user_id": user.id, "is_admin": user.is_admin}
    )
    return _to_user_admin_read(user)
