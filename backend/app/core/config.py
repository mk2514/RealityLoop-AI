from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RealityLoop API"
    environment: str = "development"
    log_level: str = "INFO"
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_database: str = "realityloop"
    mongo_username: str = "realityloop-local"
    mongo_password: str = "replace-with-a-local-mongodb-password"
    mongo_auth_source: str = "admin"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint_url: str = "http://localhost:9000"
    minio_bucket: str = "realityloop"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
