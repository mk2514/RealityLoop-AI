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
    sensor_import_max_file_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)
    sensor_import_max_rows: int = Field(default=50_000, gt=0, le=1_000_000)
    sensor_import_preview_rows: int = Field(default=25, gt=0, le=100)
    sensor_import_batch_size: int = Field(default=250, gt=0, le=2_000)
    sensor_import_error_url_ttl_seconds: int = Field(default=300, gt=0, le=900)
    device_batch_max_readings: int = Field(default=500, gt=0, le=5_000)
    device_batch_max_bytes: int = Field(default=256 * 1024, gt=0, le=5 * 1024 * 1024)
    device_future_tolerance_seconds: int = Field(default=300, ge=0, le=86_400)
    sensor_stale_multiplier: float = Field(default=3, gt=0, le=100)
    mqtt_enabled: bool = False
    mqtt_broker_url: str = ""
    mqtt_ca_file: str = ""
    mqtt_client_cert_file: str = ""
    mqtt_client_key_file: str = ""
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_queue_capacity: int = Field(default=1_000, gt=0, le=100_000)
    mqtt_message_max_bytes: int = Field(default=64 * 1024, gt=0, le=1024 * 1024)
    edge_buffer_max_rows: int = Field(default=100_000, gt=0, le=1_000_000)
    edge_batch_max_readings: int = Field(default=100, gt=0, le=5_000)
    edge_batch_max_bytes: int = Field(default=128 * 1024, gt=0, le=5 * 1024 * 1024)
    edge_retry_base_seconds: float = Field(default=1, gt=0, le=300)
    edge_retry_max_seconds: float = Field(default=60, gt=0, le=3600)
    simulation_max_time_seconds: float = Field(default=86_400, gt=0, le=31_536_000)
    simulation_max_events: int = Field(default=100_000, gt=0, le=1_000_000)
    simulation_max_event_log_bytes: int = Field(default=25 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)
    simulation_wall_timeout_seconds: int = Field(default=300, gt=0, le=3_600)
    dashboard_max_range_seconds: int = Field(default=31 * 24 * 60 * 60, gt=0, le=365 * 24 * 60 * 60)
    dashboard_raw_max_rows: int = Field(default=5_000, gt=0, le=100_000)
    dashboard_max_buckets: int = Field(default=1_000, gt=0, le=10_000)
    dashboard_export_max_rows: int = Field(default=10_000, gt=0, le=100_000)
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
        if self.mqtt_enabled:
            if not self.mqtt_broker_url.startswith("mqtts://"):
                raise ValueError("MQTT_BROKER_URL must use mqtts:// when MQTT is enabled.")
            if bool(self.mqtt_client_cert_file) != bool(self.mqtt_client_key_file):
                raise ValueError(
                    "MQTT_CLIENT_CERT_FILE and MQTT_CLIENT_KEY_FILE must be configured together."
                )
            if bool(self.mqtt_username) != bool(self.mqtt_password):
                raise ValueError("MQTT_USERNAME and MQTT_PASSWORD must be configured together.")
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
