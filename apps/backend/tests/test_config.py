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
