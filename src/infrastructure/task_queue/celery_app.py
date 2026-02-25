import logging

logger = logging.getLogger(__name__)

try:
    from celery import Celery
    from src.infrastructure.config.settings import get_settings

    settings = get_settings()

    celery_app = Celery(
        "networking_engine",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_default_retry_delay=30,
        task_max_retries=3,
        broker_connection_retry_on_startup=True,
    )

    CELERY_AVAILABLE = True
    logger.info("Celery configured with broker: %s", settings.celery_broker_url)

except Exception as e:
    celery_app = None  # type: ignore[assignment]
    CELERY_AVAILABLE = False
    logger.warning("Celery not available (Redis may not be running): %s", e)
