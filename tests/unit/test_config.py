import os

import pytest

import app.config
from app.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(app.config, "_CONFIG_FILE", tmp_path / "absent.yaml")
    prefixes = tuple(name.upper() for name in app.config.Settings.model_fields)
    for key in list(os.environ):
        if key.upper().startswith(prefixes):
            monkeypatch.delenv(key)
    app.config.get_settings.cache_clear()


class TestSettingsDefaults:
    def test_default_app_name(self):
        settings = Settings()
        assert settings.app_name == "Nexa-Client-BE"

    def test_default_app_env(self):
        settings = Settings()
        assert settings.app_env == "development"

    def test_default_is_development(self):
        settings = Settings()
        assert settings.is_development is True

    def test_default_app_port(self):
        settings = Settings()
        assert settings.app_port == 8002

    def test_default_auth_collection(self):
        settings = Settings()
        assert settings.pocketbase_auth_collection == "users"


class TestCorsOrigins:
    def test_parses_comma_separated(self):
        settings = Settings(allowed_origins="http://localhost:3000,http://example.com")
        assert settings.cors_origins == ["http://localhost:3000", "http://example.com"]

    def test_strips_whitespace(self):
        settings = Settings(allowed_origins="http://a.com , http://b.com")
        assert settings.cors_origins == ["http://a.com", "http://b.com"]

    def test_filters_empty(self):
        settings = Settings(allowed_origins="http://a.com,,http://b.com")
        assert settings.cors_origins == ["http://a.com", "http://b.com"]


class TestIsDevelopment:
    def test_development_true(self):
        settings = Settings(app_env="development")
        assert settings.is_development is True

    def test_production_false(self):
        settings = Settings(app_env="production")
        assert settings.is_development is False

    def test_staging_false(self):
        settings = Settings(app_env="staging")
        assert settings.is_development is False


class TestNestedSettings:
    def test_logging_defaults(self):
        settings = Settings()
        assert settings.logging.level == "INFO"
        assert settings.logging.loki_enabled is False

    def test_storage_defaults(self):
        settings = Settings()
        assert settings.storage.region == "us-east-1"
        assert settings.storage.presign_expiry_seconds == 900

    def test_storage_max_file_bytes(self):
        settings = Settings()
        assert settings.storage.max_file_bytes == 10 * 1024 * 1024


def test_yaml_and_environment_precedence(monkeypatch, tmp_path):
    config = tmp_path / "settings.yaml"
    config.write_text("app_port: 9001\n")
    monkeypatch.setattr(app.config, "_CONFIG_FILE", config)
    assert Settings().app_port == 9001
    monkeypatch.setenv("APP_PORT", "9002")
    assert Settings().app_port == 9002
    assert Settings(app_port=9003).app_port == 9003
