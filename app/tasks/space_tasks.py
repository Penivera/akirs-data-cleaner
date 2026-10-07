"""Celery task definitions."""
import asyncio
from typing import List, Optional

from app.tasks.celery_app import celery
from app.services.space_processor import process_space_files


def _run_async(coro):
    """Run an async coroutine, handling both Celery worker threads and active event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


@celery.task(
    name="cowork.process_space_files",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def process_space_files_task(
    self,
    task_id: str,
    space_id: str,
    file_ids: List[str],
    runner_user_id: int,
    owner_user_id: int,
    runner_email: Optional[str] = None,
    runner_name: Optional[str] = None,
    space_name: str = "",
    notify_email: bool = False,
) -> dict:
    """Celery entry point: run the bulk processing pipeline in this worker."""
    from app.core import repository as repo

    try:
        return _run_async(
            process_space_files(
                task_id=task_id,
                space_id=space_id,
                file_ids=file_ids,
                runner_user_id=runner_user_id,
                owner_user_id=owner_user_id,
                runner_email=runner_email,
                runner_name=runner_name,
                space_name=space_name,
                notify_email=notify_email,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        _run_async(
            repo.set_task(task_id, space_id, runner_user_id, "failed", str(exc))
        )
        raise self.retry(exc=exc)
