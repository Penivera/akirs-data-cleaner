"""Background cleanup job that removes stale uploads, cleaned files, and reports."""
import logging
import os
import time
from typing import Optional, Set

from app.core.config import settings

logger = logging.getLogger("app.cleanup")


async def remove_uploaded_file(saved_path: Optional[str]) -> None:
    """Delete an uploaded source file once its processing result is ready.

    Called as a hook whenever a cleaned output is produced, so the original
    upload does not linger in uploads/ indefinitely.
    """
    if not saved_path:
        return
    try:
        if os.path.exists(saved_path):
            os.remove(saved_path)
            logger.info("Removed uploaded file %s (result ready)", saved_path)
    except OSError as exc:
        logger.warning("Failed to remove uploaded file %s: %r", saved_path, exc)


async def cleanup_stale_files() -> dict:
    """
    Delete files older than settings.cleanup_max_age_hours from uploads/,
    cleaned/, and reports/ directories.

    Returns a summary dict with counts of deleted files.
    """
    if not settings.cleanup_enabled:
        logger.info("Cleanup job is disabled, skipping.")
        return {"enabled": False}

    max_age_seconds = settings.cleanup_max_age_hours * 3600
    now = time.time()
    cutoff = now - max_age_seconds

    deleted_counts = {"uploads": 0, "cleaned": 0, "reports": 0, "errors": 0}

    for dir_name in ("uploads", "cleaned", "reports"):
        if not os.path.isdir(dir_name):
            continue

        # Walk through user subdirectories
        for user_dir in os.listdir(dir_name):
            user_path = os.path.join(dir_name, user_dir)
            if not os.path.isdir(user_path):
                # Handle legacy files at the top level (pre-user-scoping)
                _maybe_delete_file(user_path, cutoff, deleted_counts, dir_name)
                continue

            for fname in os.listdir(user_path):
                fpath = os.path.join(user_path, fname)
                _maybe_delete_file(fpath, cutoff, deleted_counts, dir_name)

            # Remove empty user directories
            try:
                if not os.listdir(user_path):
                    os.rmdir(user_path)
                    logger.debug("Removed empty directory %s", user_path)
            except OSError:
                pass

    # Also clean up expired state entries
    await _cleanup_state_entries(cutoff)

    logger.info(
        "Cleanup complete: uploads=%d cleaned=%d reports=%d errors=%d",
        deleted_counts["uploads"],
        deleted_counts["cleaned"],
        deleted_counts["reports"],
        deleted_counts["errors"],
    )
    return deleted_counts


def _maybe_delete_file(
    fpath: str,
    cutoff: float,
    deleted_counts: dict,
    dir_name: str,
) -> None:
    """Delete a file if it's older than the cutoff time."""
    try:
        if not os.path.isfile(fpath):
            return
        mtime = os.path.getmtime(fpath)
        if mtime < cutoff:
            os.remove(fpath)
            deleted_counts[dir_name] += 1
            logger.debug("Deleted stale file %s", fpath)
    except Exception as exc:
        deleted_counts["errors"] += 1
        logger.warning("Failed to delete %s: %r", fpath, exc)


async def _cleanup_state_entries(cutoff: float) -> None:
    """Remove expired work items and tasks from the database."""
    from app.core import repository as repo

    try:
        deleted = await repo.purge_older_than(cutoff)
        if deleted:
            logger.info("Purged %d expired work item(s)/task(s).", deleted)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to purge expired state: %r", exc)
