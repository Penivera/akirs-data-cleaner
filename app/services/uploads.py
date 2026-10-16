"""Upload ingestion helpers.

The heavyweight part of an upload (health scanning, header detection, field
mapping, branch detection) does not belong in the request. These helpers let an
endpoint accept a file quickly — validate, stream it to disk while computing a
hash for de-duplication — and hand the analysis to a background task, so the
browser gets a card back immediately and polls for the result.
"""
import hashlib
import os

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

# Shown on a work item while its background analysis is running.
ANALYSING_STATUS = "Analysing..."

CHUNK_SIZE = 1024 * 1024


async def stream_upload_to_disk(upload: UploadFile, dest_path: str) -> tuple[str, int]:
    """Stream an upload to disk in chunks, returning its SHA-256 and size.

    Enforces the configured maximum size mid-stream so an oversized file never
    lands fully on disk. Raises HTTPException(413) when the cap is exceeded.
    """
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
    hasher = hashlib.sha256()
    size = 0

    with open(dest_path, "wb") as out:
        while chunk := await upload.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_size_bytes:
                out.close()
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(
                        "File size exceeds the maximum allowed size of "
                        f"{settings.max_upload_size_mb}MB"
                    ),
                )
            hasher.update(chunk)
            out.write(chunk)

    return hasher.hexdigest(), size
