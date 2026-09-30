"""File upload validation helpers."""
import os

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings


def validate_upload(file: UploadFile) -> None:
    """
    Validate an uploaded file for type and size.

    Raises HTTPException if validation fails.
    """
    # Check file extension
    filename = file.filename or ""
    _, ext = os.path.splitext(filename.lower())
    allowed = {e.strip().lower() for e in settings.allowed_extensions.split(",")}

    if ext not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' is not allowed. Allowed types: {', '.join(sorted(allowed))}",
        )

    # Check file size (if we can determine it from the headers)
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

    # The UploadFile object doesn't always expose size upfront, so we check
    # the Content-Length header via the file's internal state if available.
    if hasattr(file, "size") and file.size is not None:
        if file.size > max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds the maximum allowed size of {settings.max_upload_size_mb}MB",
            )
