import pytest

from waterfall.core.config import Settings, _validate_settings


@pytest.mark.parametrize("secret_key", ["", "   ", "change-me", " change-me "])
def test_settings_reject_missing_or_placeholder_secret(secret_key: str) -> None:
    settings = Settings(_env_file=None, APP_ENV="dev", SECRET_KEY=secret_key)

    with pytest.raises(ValueError, match="SECRET_KEY must be set"):
        _validate_settings(settings)


def test_settings_accepts_configured_secret() -> None:
    settings = Settings(_env_file=None, APP_ENV="dev", SECRET_KEY="test-secret")

    assert _validate_settings(settings) is settings