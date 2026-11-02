from celery import Celery

from app.core.config import get_settings

settings = get_settings()
deployed_on_vercel = settings.environment.lower() in {"production", "preview"}

celery_app = Celery(
    "realityloop",
    broker="vercel://" if deployed_on_vercel else settings.redis_url,
    backend="vercel-runtime-cache://" if deployed_on_vercel else settings.redis_url.replace("/0", "/1"),
)
celery_app.conf.update(
    accept_content=["json"],
    result_accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="realityloop.infrastructure.healthcheck")
def healthcheck() -> str:
    return "ok"
