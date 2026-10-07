"""Celery application: Redis broker/result backend (self-hosted)."""
from celery import Celery

from app.core.config import settings

celery = Celery(
    "akirs",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.space_tasks"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    worker_prefetch_multiplier=1,
)
