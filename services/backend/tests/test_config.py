import pytest
from pydantic import ValidationError

from app.config import DEFAULT_DATABASE_URL, Settings


def test_defaults_point_at_repo_data_directory():
    assert Settings().database_url == DEFAULT_DATABASE_URL
    assert DEFAULT_DATABASE_URL.endswith("/data/greenloop.db")


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("GREENLOOP_LOG_LEVEL", "debug")
    monkeypatch.setenv("GREENLOOP_DATABASE_URL", "sqlite:///:memory:")

    settings = Settings()

    assert settings.log_level == "DEBUG"
    assert settings.database_url == "sqlite:///:memory:"


def test_invalid_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("GREENLOOP_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings()
