from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RealityLoop API"
    environment: str = "development"
    log_level: str = "INFO"
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_database: str = "realityloop"
    mongo_username: str = Field(
        default="realityloop-app",
        validation_alias="MONGO_APP_USERNAME",
    )
    mongo_password: str = Field(
        default="replace-with-a-local-application-database-password",
        validation_alias="MONGO_APP_PASSWORD",
    )
    mongo_auth_source: str = ""
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint_url: str = "http://localhost:9000"
    minio_bucket: str = "realityloop"
    session_cookie_name: str = "rl_session"
    csrf_cookie_name: str = "rl_csrf"
    session_ttl_seconds: int = Field(default=60 * 60 * 12, gt=0)
    verification_ttl_seconds: int = Field(default=60 * 60 * 24, gt=0)
    password_reset_ttl_seconds: int = Field(default=60 * 60, gt=0)
    cookie_secure: bool = False
    public_app_url: str = "http://localhost:8080"
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=1025, gt=0, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = "RealityLoop AI <no-reply@realityloop.local>"
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    auth_rate_limit_window_seconds: int = Field(default=900, gt=0)
    auth_login_limit: int = Field(default=10, gt=0)
    auth_register_limit: int = Field(default=5, gt=0)
    auth_recovery_limit: int = Field(default=4, gt=0)
    auth_verification_limit: int = Field(default=5, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def production_requires_secure_configuration(self) -> "Settings":
        if self.environment.lower() == "production":
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be enabled in production.")
            if not self.public_app_url.startswith("https://"):
                raise ValueError("PUBLIC_APP_URL must use HTTPS in production.")
            if (
                not self.smtp_host
                or self.smtp_host.lower() in {"localhost", "mailpit"}
                or not self.smtp_sender
            ):
                raise ValueError("SMTP_HOST and SMTP_SENDER are required in production.")
            if not (self.smtp_starttls or self.smtp_ssl):
                raise ValueError("Production SMTP must use STARTTLS or SSL.")
            if (
                not self.mongo_username
                or not self.mongo_password
                or self.mongo_password.startswith("replace-with-")
            ):
                raise ValueError("Production MongoDB application credentials must be configured.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
