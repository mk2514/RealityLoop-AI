import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_read_least_privilege_mongodb_application_credentials(monkeypatch) -> None:
    monkeypatch.setenv("MONGO_APP_USERNAME", "application-user")
    monkeypatch.setenv("MONGO_APP_PASSWORD", "application-password")

    settings = Settings(_env_file=None)

    assert settings.mongo_username == "application-user"
    assert settings.mongo_password == "application-password"


def test_production_settings_reject_insecure_authentication_configuration() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            cookie_secure=True,
            public_app_url="https://app.example.test",
            smtp_host="smtp.example.test",
            smtp_starttls=True,
        )


def test_production_settings_accept_secure_cookie_smtp_and_database_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MONGO_APP_USERNAME", "app-user")
    monkeypatch.setenv("MONGO_APP_PASSWORD", "strong-application-password")
    settings = Settings(
        _env_file=None,
        environment="production",
        cookie_secure=True,
        public_app_url="https://app.example.test",
        smtp_host="smtp.example.test",
        smtp_starttls=True,
    )

    assert settings.environment == "production"


def test_production_settings_reject_local_mailpit(monkeypatch) -> None:
    monkeypatch.setenv("MONGO_APP_USERNAME", "app-user")
    monkeypatch.setenv("MONGO_APP_PASSWORD", "strong-application-password")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            cookie_secure=True,
            public_app_url="https://app.example.test",
            smtp_host="mailpit",
            smtp_starttls=True,
        )
