"""Celery application and tasks package."""
from app.tasks.celery_app import celery

__all__ = ["celery"]
