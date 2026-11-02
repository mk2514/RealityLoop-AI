from app.core.config import Settings


def test_settings_read_mongodb_credentials_from_example_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("MONGO_ROOT_USERNAME", "local-user")
    monkeypatch.setenv("MONGO_ROOT_PASSWORD", "local-password")

    settings = Settings(_env_file=None)

    assert settings.mongo_username == "local-user"
    assert settings.mongo_password == "local-password"
