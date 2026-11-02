from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RealityLoop API"
    environment: str = "development"
    mongo_only_infra: bool = False
    log_level: str = "INFO"
    mongo_uri: str = Field(default="", validation_alias="MONGO_URI")
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
    frontend_origins: str = Field(default="", validation_alias="FRONTEND_ORIGINS")
    s3_endpoint_url: str = Field(default="", validation_alias="S3_ENDPOINT_URL")
    s3_region: str = Field(default="us-east-1", validation_alias="S3_REGION")
    s3_bucket: str = Field(default="", validation_alias="S3_BUCKET")
    s3_access_key_id: str = Field(default="", validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", validation_alias="S3_SECRET_ACCESS_KEY")
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
        populate_by_name=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def production_requires_secure_configuration(self) -> "Settings":
        if self.environment.lower() in {"production", "preview"}:
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be enabled in production.")
            if not self.public_app_url.startswith("https://"):
                raise ValueError("PUBLIC_APP_URL must use HTTPS in production.")
            if not self.cors_origins or any(
                not origin.startswith("https://") for origin in self.cors_origins
            ):
                raise ValueError(
                    "FRONTEND_ORIGINS must list HTTPS frontend origins in production."
                )
            if (
                not self.smtp_host
                or self.smtp_host.lower() in {"localhost", "mailpit"}
                or not self.smtp_sender
            ):
                raise ValueError("SMTP_HOST and SMTP_SENDER are required in production.")
            if not (self.smtp_starttls or self.smtp_ssl):
                raise ValueError("Production SMTP must use STARTTLS or SSL.")
            if self.mongo_uri:
                if (
                    not self.mongo_uri.startswith("mongodb+srv://")
                    or "@" not in self.mongo_uri
                ):
                    raise ValueError(
                        "Production MONGO_URI must be an authenticated mongodb+srv:// URI."
                    )
            elif (
                self.mongo_host.lower() in {"localhost", "127.0.0.1"}
                or not self.mongo_username
                or not self.mongo_password
                or self.mongo_password.startswith("replace-with-")
            ):
                raise ValueError(
                    "Production MongoDB requires an authenticated remote cluster URI."
                )
            if not self.mongo_only_infra and not self.redis_url.startswith("rediss://"):
                raise ValueError("Production REDIS_URL must use TLS (rediss://).")
            if not self.mongo_only_infra and not (self.s3_bucket and self.s3_access_key_id and self.s3_secret_access_key):
                raise ValueError(
                    "Production S3-compatible storage bucket credentials must be configured."
                )
            if self.s3_endpoint_url and not self.s3_endpoint_url.startswith("https://"):
                raise ValueError("Production S3_ENDPOINT_URL must use HTTPS.")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.frontend_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
