import logging
import smtplib
from urllib.error import URLError
from urllib.request import urlopen

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


def check_database() -> bool:
    try:
        get_database().command("ping")
        return True
    except PyMongoError:
        logger.warning("Readiness check failed for mongodb")
        return False


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
    try:
        with urlopen(f"{get_settings().minio_endpoint_url}/minio/health/ready", timeout=1) as result:
            return result.status == 200
    except (OSError, URLError, TimeoutError):
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
    dependencies = {
        "mongodb": check_database(),
        "redis": check_redis(),
        "object_storage": check_object_storage(),
        "smtp": check_smtp(),
    }
    ready = all(dependencies.values())
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "dependencies": {
            name: "ready" if available else "unavailable"
            for name, available in dependencies.items()
        },
        "request_id": request.state.request_id,
    }
