import logging
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4

import redis
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from redis.backoff import ExponentialBackoff
from redis.commands.core import Script
from redis.exceptions import RedisError
from redis.retry import Retry
from sqlalchemy.orm import Session

from waterfall.api.dependencies import get_current_active_user, get_current_admin_user
from waterfall.api.pagination import ListParams, list_params
from waterfall.core.config import MEMORY_REDIS_URL_SCHEME, get_settings
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
    Token,
    UserAdminListRead,
    UserAdminRead,
    UserCreate,
    UserRead,
    UserRoleUpdate,
    UserStatusUpdate,
)
from waterfall.services import apply_pagination

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)
REFRESH_COOKIE_NAME = "waterfall_refresh"

# Short enough to never hold up a login request if Redis is unreachable or slow.
_REDIS_SOCKET_TIMEOUT_SECONDS = 2
# Detects a connection that died while idle (Redis restart, server-side idle timeout)
# before it is handed to a login request, instead of surfacing it as a fail-closed 503.
_REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30
_RATE_LIMIT_KEY_PREFIX = "login_rate_limit:"
# Key count above which the in-process backend reclaims elapsed windows. High enough that a
# normal login load never sweeps, low enough to bound memory under a flood of one-shot keys.
_MEMORY_SWEEP_WATERMARK = 1024

# Prune the window, count, and record the attempt in one atomic server-side step.
# A read-modify-write over separate round-trips lets concurrent logins all observe the
# same pre-increment count and be admitted together (measured: 16 grants for a limit of
# 5 under 40 concurrent calls); it also leaves the key without a TTL, leaking forever,
# if the process dies between ZADD and EXPIRE.
#
# Semantics are deliberately identical to the previous sequence: a *refused* attempt is
# not recorded, so being rate limited does not extend the window.
#   KEYS[1] = rate limit key
#   ARGV[1] = window start score   ARGV[2] = max attempts   ARGV[3] = now (score)
#   ARGV[4] = unique member id     ARGV[5] = key TTL in seconds
# Returns 1 when the attempt is allowed (and recorded), 0 when it is refused.
_RATE_LIMIT_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


class RateLimiterUnavailableError(Exception):
    """Raised by LoginRateLimiter.allow() when its Redis backend can't be reached.

    This is distinct from "rate limited": the caller must fail closed (reject the
    login attempt, e.g. with a 503) rather than let a login through unchecked.
    """


class _InMemoryRateLimitBackend:
    """Sliding-window limiter held in this process only, for `REDIS_URL=memory://`.

    Counters are per-process and lost on restart, so this is for a single-instance
    checkout without infrastructure -- the same trade-off as defaulting to sqlite. The
    lock matters even there: sync endpoints run in a threadpool, so concurrent logins on
    one key would otherwise all read the same pre-increment count and overshoot the
    limit, which is exactly what the Redis backend uses an atomic Lua script to prevent.
    """

    def __init__(self) -> None:
        self._attempts: dict[str, deque[datetime]] = {}
        self._lock = Lock()

    def allow(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        with self._lock:
            # Read the clock under the lock: two threads timestamping outside it can append
            # out of order, and the prune below stops at the first non-expired entry, so an
            # older attempt behind a newer one would outlive its window.
            now = datetime.now(UTC)
            window_start = now - timedelta(seconds=window_seconds)
            attempts = self._attempts.get(key)
            if attempts is None:
                attempts = self._attempts[key] = deque()
            while attempts and attempts[0] < window_start:
                attempts.popleft()
            if len(attempts) >= max_attempts:
                return False
            attempts.append(now)
            if len(self._attempts) > _MEMORY_SWEEP_WATERMARK:
                self._sweep_locked(window_start)
            return True

    def _sweep_locked(self, window_start: datetime) -> None:
        """Drop keys whose window has fully elapsed. Caller must hold the lock.

        The key embeds the caller-supplied `username`, so an anonymous caller posting a
        fresh one each time would otherwise grow this dict forever -- the leak the Redis
        backend avoids by letting EXPIRE reclaim the key. Sweeping above a watermark keeps
        the cost amortized while bounding the dict to the keys active in the window.
        """
        for key in [k for k, v in self._attempts.items() if not v or v[-1] < window_start]:
            del self._attempts[key]

    def ping(self) -> None:
        """No-op: an in-process dict has no backend that can be unreachable."""

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()


class _RedisRateLimitBackend:
    """Sliding-window login attempt limiter backed by a Redis sorted set.

    Shared across processes/instances, unlike _InMemoryRateLimitBackend. Each
    key maps to a sorted set of attempt timestamps (score = attempt time, member =
    a random id to avoid collisions between attempts in the same instant).
    `allow()` prunes entries older than the window, counts what's left, and either
    records a new attempt or refuses -- the same functional behaviour as the
    per-key deque, but shared, and executed as a single atomic Lua script so that
    concurrent logins on the same key cannot all read a stale count and overshoot the
    limit.

    Connection failures raise RateLimiterUnavailableError (fail-closed for callers
    such as `login()`). `clear()` is a test-only utility with the opposite policy; see
    its docstring.
    """

    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        self._allow_script: Script | None = None

    def _get_client(self) -> redis.Redis:
        # Lazy: reads the Redis settings on first use rather than at import time (this
        # class is instantiated once, at module load), so it picks up whatever
        # REDIS_URL/REDIS_PASSWORD the process actually starts with.
        if self._client is None:
            settings = get_settings()
            self._client = redis.Redis.from_url(
                settings.redis_url,
                # redis-py keeps a password carried by the URL when this is None, so an
                # existing `redis://:pwd@host` URL still works.
                password=settings.redis_password,
                socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
                socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
                health_check_interval=_REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
                retry=Retry(ExponentialBackoff(), 1),
            )
        return self._client

    def _get_allow_script(self) -> Script:
        # register_script() only computes the SHA client-side; redis-py transparently
        # falls back to EVAL on NOSCRIPT, so this survives a Redis restart flushing the
        # script cache.
        if self._allow_script is None:
            self._allow_script = self._get_client().register_script(_RATE_LIMIT_LUA)
        return self._allow_script

    def allow(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        now = datetime.now(UTC).timestamp()
        window_start = now - window_seconds
        redis_key = f"{_RATE_LIMIT_KEY_PREFIX}{key}"
        try:
            script = self._get_allow_script()
            allowed = script(
                keys=[redis_key],
                args=[window_start, max_attempts, now, uuid4().hex, window_seconds + 1],
            )
        # ValueError, not RedisError: redis-py raises it from from_url() for a malformed
        # URL (e.g. a REDIS_URL with no scheme), the most banal misconfiguration there
        # is. Letting it escape would turn the documented fail-closed 503 into a 500 that
        # violates the OpenAPI contract.
        except (RedisError, ValueError) as exc:
            raise RateLimiterUnavailableError(
                "Login rate limiter Redis backend is unreachable"
            ) from exc
        return bool(allowed)

    def ping(self) -> None:
        """Raise RateLimiterUnavailableError unless Redis answers PING. Read-only.

        Exists for the readiness probe (`GET /health/ready`), which reports on the very
        client the login path depends on rather than opening a connection of its own: a
        probe on a separate client could stay green -- different pool, different socket
        state -- while every login fails closed here.
        """
        try:
            self._get_client().ping()
        # Same two exception types, for the same reasons, as allow(): a malformed
        # REDIS_URL surfaces from from_url() as ValueError, not RedisError.
        except (RedisError, ValueError) as exc:
            raise RateLimiterUnavailableError(
                "Login rate limiter Redis backend is unreachable"
            ) from exc

    def clear(self) -> None:
        """Drop every login rate limit counter. Test utility -- no production caller.

        Two deliberate properties, neither of which suits production use:

        - It swallows connection errors instead of failing closed like `allow()`, because
          an autouse fixture calls it before every test in the suite, most of which have
          nothing to do with auth.
        - It deletes *all* `login_rate_limit:*` keys of the configured Redis database, so
          running the tests against the same Redis database as a dev API wipes that API's
          live counters. Point `TEST_REDIS_URL` at a separate database to avoid it.
        """
        try:
            client = self._get_client()
            # scan_iter, not keys(): KEYS blocks the Redis server for the whole scan.
            keys = cast(
                Iterable[bytes], client.scan_iter(match=f"{_RATE_LIMIT_KEY_PREFIX}*", count=500)
            )
            for key in keys:
                client.delete(key)
        except (RedisError, ValueError):
            pass


class LoginRateLimiter:
    """Dispatches to the rate limit backend named by REDIS_URL's scheme.

    `memory://` gets the in-process limiter, anything else a real Redis -- the same
    URL-scheme selection the database layer uses to run on sqlite or Postgres from one
    code path. Resolution is lazy so the process picks up the REDIS_URL it actually
    starts with, not whatever was set when this module was imported.
    """

    def __init__(self) -> None:
        self._backend: _InMemoryRateLimitBackend | _RedisRateLimitBackend | None = None
        self._lock = Lock()

    def _get_backend(self) -> _InMemoryRateLimitBackend | _RedisRateLimitBackend:
        with self._lock:
            if self._backend is None:
                url = get_settings().redis_url
                if urlsplit(url).scheme == MEMORY_REDIS_URL_SCHEME:
                    # The readiness probe cannot surface this -- an in-process limiter is
                    # never "down" -- so this log is the only signal that attempt counters
                    # are per-process and reset on restart. Settings validation already
                    # rejects memory:// outside dev/test; this covers dev itself.
                    logger.warning(
                        "Login rate limiter is in-process (REDIS_URL=%s): counters are not "
                        "shared between workers and are lost on restart",
                        MEMORY_REDIS_URL_SCHEME + "://",
                    )
                    self._backend = _InMemoryRateLimitBackend()
                else:
                    self._backend = _RedisRateLimitBackend()
            return self._backend

    def allow(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        return self._get_backend().allow(key, max_attempts, window_seconds)

    def ping(self) -> None:
        self._get_backend().ping()

    def clear(self) -> None:
        """Drop every login rate limit counter. Test utility -- no production caller.

        Fails silently rather than closed, and on the Redis backend wipes the counters of
        every app sharing that database; see _RedisRateLimitBackend.clear().
        """
        self._get_backend().clear()


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


def _issue_access_token(user: User) -> Token:
    settings = get_settings()
    return Token(
        access_token=create_access_token(user.email, token_version=user.token_version),
        expiresIn=settings.access_token_expire_minutes * 60,
    )


def _set_refresh_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=create_refresh_token(user.email, token_version=user.token_version),
        httponly=True,
        secure=settings.app_env not in {"dev", "test"},
        samesite="lax",
        path="/auth",
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
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    settings = get_settings()
    client_ip = request.client.host if request.client is not None else "unknown"
    limiter_key = f"{client_ip}:{normalize_email(form_data.username)}"

    try:
        rate_limit_allowed = login_rate_limiter.allow(
            limiter_key,
            max_attempts=settings.auth_rate_limit_attempts,
            window_seconds=settings.auth_rate_limit_window_seconds,
        )
    except RateLimiterUnavailableError as exc:
        # Fail-closed means a Redis misconfiguration blocks 100% of logins, so this log
        # line is the only diagnostic available: carry the underlying cause and its
        # traceback. Never the Redis URL itself -- it may embed a password.
        logger.error(
            "auth.login.rate_limiter_unavailable",
            extra={
                "email": normalize_email(form_data.username),
                "error": str(exc.__cause__ or exc),
            },
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login temporarily unavailable",
        ) from exc

    if not rate_limit_allowed:
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
    _set_refresh_cookie(response, user)
    return _issue_access_token(user)


@router.post("/refresh", response_model=Token)
def refresh_token(request: Request, response: Response, db: Session = Depends(get_db)) -> Token:
    refresh_token_value = request.cookies.get(REFRESH_COOKIE_NAME)
    decoded = decode_refresh_token(refresh_token_value) if refresh_token_value else None
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

    logger.info("auth.refresh.success", extra={"email": user.email})
    _set_refresh_cookie(response, user)
    return _issue_access_token(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/auth")


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


@router.get("/users", response_model=UserAdminListRead)
def list_users(
    params: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> UserAdminListRead:
    result = apply_pagination(
        db.query(User),
        params,
        sortable={
            "email": User.email,
            "created_at": User.created_at,
            "is_active": User.is_active,
        },
        tiebreaker=User.id,
        searchable=[User.email],
    )
    return UserAdminListRead(
        items=[_to_user_admin_read(item) for item in result.rows],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post("/users", response_model=UserAdminRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> UserAdminRead:
    normalized_email = normalize_email(payload.email)
    if _get_user_by_email(db, normalized_email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("auth.admin_user_created", extra={"target_user_id": user.id})
    return _to_user_admin_read(user)


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


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if current_admin.id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete self")

    db.delete(user)
    db.commit()
    logger.info("auth.admin_user_deleted", extra={"target_user_id": user_id})
