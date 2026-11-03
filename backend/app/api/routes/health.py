import logging
import smtplib

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Request, Response
from pymongo.errors import PyMongoError
from redis import Redis

from app.core.config import get_settings
from app.db.client import get_database

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/live")
def liveness(request: Request) -> dict[str, str]:
    return {"status": "alive", "request_id": request.state.request_id}


def check_database_detail() -> tuple[bool, str | None, int | None]:
    try:
        get_database().command("ping")
        return True, None, None
    except PyMongoError as error:
        logger.warning(
            "Readiness check failed for mongodb error_type=%s error_code=%s",
            type(error).__name__,
            getattr(error, "code", None),
        )
        return False, type(error).__name__, getattr(error, "code", None)


def check_database() -> bool:
    return check_database_detail()[0]


def check_redis() -> bool:
    client = Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        return bool(client.ping())
    except Exception:
        logger.warning("Readiness check failed for redis")
        return False
    finally:
        client.close()


def check_object_storage() -> bool:
    settings = get_settings()
    if not settings.s3_bucket:
        logger.warning("Readiness check failed for object storage")
        return False
    try:
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            config=Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 1}),
        )
        client.head_bucket(Bucket=settings.s3_bucket)
        return True
    except (BotoCoreError, ClientError):
        logger.warning("Readiness check failed for object storage")
        return False


def check_smtp() -> bool:
    settings = get_settings()
    try:
        if settings.smtp_ssl:
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=1,
            ) as smtp:
                smtp.ehlo()
        else:
            with smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=1,
            ) as smtp:
                smtp.ehlo()
                if settings.smtp_starttls:
                    smtp.starttls()
                    smtp.ehlo()
        return True
    except (OSError, smtplib.SMTPException):
        logger.warning("Readiness check failed for SMTP")
        return False


@router.get("/ready")
def readiness(request: Request, response: Response) -> dict[str, object]:
    mongodb_ready = check_database()
    mongodb_error_type = None
    mongodb_error_code = None
    if not mongodb_ready:
        _, mongodb_error_type, mongodb_error_code = check_database_detail()
    dependencies = {
        "mongodb": mongodb_ready,
        "smtp": check_smtp(),
    }
    if not get_settings().mongo_only_infra:
        dependencies.update(redis=check_redis(), object_storage=check_object_storage())
    ready = all(dependencies.values())
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "dependencies": {
            name: "ready" if available else "unavailable"
            for name, available in dependencies.items()
        },
        **(
            {
                "mongodb_error": {
                    "type": mongodb_error_type,
                    "code": mongodb_error_code,
                }
            }
            if not mongodb_ready
            else {}
        ),
        "request_id": request.state.request_id,
    }
