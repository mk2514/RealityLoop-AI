import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db import client as database_client


def test_settings_read_least_privilege_mongodb_application_credentials(monkeypatch) -> None:
    monkeypatch.setenv("MONGO_APP_USERNAME", "application-user")
    monkeypatch.setenv("MONGO_APP_PASSWORD", "application-password")

    settings = Settings(_env_file=None)

    assert settings.mongo_username == "application-user"
    assert settings.mongo_password == "application-password"


def test_mongo_client_uses_the_configured_remote_uri(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        mongo_uri="mongodb+srv://app:password@cluster.example.test/realityloop",
    )
    arguments = {}
    client = object()

    def create_client(*args, **kwargs):
        arguments["args"] = args
        arguments["kwargs"] = kwargs
        return client

    monkeypatch.setattr(database_client, "get_settings", lambda: settings)
    monkeypatch.setattr(database_client, "MongoClient", create_client)
    database_client.get_mongo_client.cache_clear()
    try:
        assert database_client.get_mongo_client() is client
    finally:
        database_client.get_mongo_client.cache_clear()

    assert arguments["args"] == (
        "mongodb+srv://app:password@cluster.example.test/realityloop",
    )
    assert arguments["kwargs"]["appname"] == settings.app_name


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


def test_production_settings_accept_secure_cookie_smtp_and_database_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        cookie_secure=True,
        public_app_url="https://app.example.test",
        smtp_host="smtp.example.test",
        smtp_starttls=True,
        mongo_uri="mongodb+srv://app-user:password@cluster.example.test/realityloop",
        redis_url="rediss://user:password@redis.example.test:6380/0",
        s3_bucket="realityloop-assets",
        s3_access_key_id="test-access-key",
        s3_secret_access_key="test-secret-key",
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
