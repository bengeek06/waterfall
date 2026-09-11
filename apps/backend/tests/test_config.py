from collections.abc import Iterator

import pytest

from waterfall.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache_after_test() -> Iterator[None]:
    """Drop the cached Settings once monkeypatch has restored the environment.

    get_settings is lru_cached, so a test that successfully builds Settings from a patched
    environment leaves that object in the cache for the rest of the session -- every later
    test would then run as, say, APP_ENV=prod against an unreachable Redis.
    """
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("secret_key", ["", "   ", "change-me", " change-me "])
def test_settings_reject_missing_or_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch, secret_key: str
) -> None:
    monkeypatch.setenv("SECRET_KEY", secret_key)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="SECRET_KEY must be set"):
        get_settings()


def test_settings_accepts_configured_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    get_settings.cache_clear()

    assert get_settings().secret_key == "test-secret"


@pytest.mark.parametrize("variable", ["GARAGE_ACCESS_KEY_ID", "GARAGE_SECRET_ACCESS_KEY"])
def test_settings_reject_missing_object_storage_credentials(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    """Fail at boot rather than at the first import.

    Empty credentials still produce a well-formed SigV4 signature, so without this the
    only symptom of a native dev run without a configured Garage would be an opaque 503
    on the first upload, long after the cause.
    """
    monkeypatch.setenv(variable, "")
    get_settings.cache_clear()
    with pytest.raises(
        ValueError, match="GARAGE_ACCESS_KEY_ID and GARAGE_SECRET_ACCESS_KEY must be set"
    ):
        get_settings()


@pytest.mark.parametrize("app_env", ["prod", "staging"])
def test_settings_reject_in_process_rate_limiter_outside_dev(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    """Fail at boot rather than silently weaken a security control.

    An unset REDIS_URL yields memory://, whose counters are per-process and lost on
    restart. Nothing downstream would report it: the readiness probe cannot see it, so the
    only symptom would be an attacker getting attempts x workers tries per window.
    """
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("REDIS_URL", "memory://")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="development-only rate limiter"):
        get_settings()


@pytest.mark.parametrize("app_env", ["dev", "test"])
def test_settings_accept_in_process_rate_limiter_in_dev(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("REDIS_URL", "memory://")
    get_settings.cache_clear()

    assert get_settings().redis_url == "memory://"


def test_settings_accept_a_real_redis_url_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    get_settings.cache_clear()

    assert get_settings().redis_url == "redis://redis:6379/0"
