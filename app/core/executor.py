"""Dedicated bounded thread pool for CPU-bound work.

The application runs a single async worker. Heavy synchronous work (parsing
Excel/CSV files, record extraction, duplicate detection, writing CSV output)
would otherwise block the asyncio event loop and stall every other request.

`run_cpu` moves that work onto a small, bounded thread pool so the event loop
stays responsive. A dedicated pool is used instead of the loop's default
executor so that FastAPI's synchronous dependencies (DB auth lookups) are not
starved by long-running file processing.
"""
import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

from app.core.config import settings

T = TypeVar("T")

_executor: Optional[ThreadPoolExecutor] = None


def get_executor() -> ThreadPoolExecutor:
    """Return the shared CPU thread pool, creating it on first use."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=max(1, settings.processing_threads),
            thread_name_prefix="akirs-cpu",
        )
    return _executor


async def run_cpu(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a blocking callable on the CPU pool without blocking the event loop."""
    loop = asyncio.get_running_loop()
    if kwargs:
        func = functools.partial(func, **kwargs)  # type: ignore[assignment]
    return await loop.run_in_executor(get_executor(), func, *args)


def shutdown_executor() -> None:
    """Release the CPU pool threads (called on application shutdown)."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None
