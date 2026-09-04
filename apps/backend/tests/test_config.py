import pytest

from waterfall.core.config import get_settings


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
