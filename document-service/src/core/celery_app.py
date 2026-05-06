from celery import Celery
from src.core.config import settings

celery_app = Celery(
    "document_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.tasks.document_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "src.tasks.document_tasks.process_document_ai": {"queue": "ai"},
    },
)
