from celery import Celery
from celery.signals import worker_ready, worker_shutdown

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "realityloop",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.worker.sensor_imports",
        "app.worker.simulation_runs",
        "app.worker.photo_analysis",
        "app.worker.twin_validations",
    ],
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


_mqtt_subscriber = None


@worker_ready.connect
def start_mqtt_ingestion(**_kwargs) -> None:
    global _mqtt_subscriber
    from app.telemetry.mqtt_subscriber import start_mqtt_subscriber

    _mqtt_subscriber = start_mqtt_subscriber()


@worker_shutdown.connect
def stop_mqtt_ingestion(**_kwargs) -> None:
    if _mqtt_subscriber is not None:
        _mqtt_subscriber.stop()
